"""
Concurrency tests with real threads and separate database connections. They need a database
with row locks and concurrent connections (PostgreSQL, as in production); on SQLite they skip.
"""

import threading
import unittest

from django.db import connection, connections
from django.test import TransactionTestCase

from live import engine, services
from live.models import ScoreEvent, TeamParticipation, TeamSubmission

from .helpers import act, correct_answer, current_question, join, make_host, new_session, refresh

POSTGRES = connection.vendor == "postgresql"


def run_threads(fn, n):
    barrier = threading.Barrier(n)
    results, errors = [], []

    def worker(i):
        try:
            barrier.wait()
            results.append(fn(i))
        except Exception as exc:  # collected and inspected by the test
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


@unittest.skipUnless(POSTGRES, "requires PostgreSQL")
class ConcurrencyTests(TransactionTestCase):
    serialized_rollback = True  # keep the seeded mission content between tests

    def setUp(self):
        from games.content import load_default

        load_default()
        self.host = make_host()
        self.session = new_session(self.host)

    def test_fifteen_simultaneous_joins_fill_exactly_ten_slots(self):
        results, errors = run_threads(lambda i: services.join_team(self.session.pk, f"Team {i}")[0].slot, 15)
        self.assertEqual(len(results), 10)
        self.assertEqual(sorted(results), list(range(1, 11)))
        self.assertEqual({e.code for e in errors}, {"FULL"})
        self.assertEqual(TeamParticipation.objects.filter(session=self.session, status="ACTIVE").count(), 10)
        self.assertEqual(refresh(self.session).version, 1 + 10)

    def test_simultaneous_joins_with_same_name(self):
        results, errors = run_threads(lambda i: services.join_team(self.session.pk, "Vector" if i % 2 else "VECTOR")[0].pk, 6)
        self.assertEqual(len(results), 1)
        self.assertEqual({e.code for e in errors}, {"NAME_TAKEN"})

    def test_duplicate_simultaneous_submissions_store_one_answer(self):
        team, _ = join(self.session, "Vector")
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        q = current_question(self.session)
        rt_id = refresh(self.session).current_runtime_id
        results, errors = run_threads(lambda i: services.submit_answer(team, rt_id, correct_answer(q))[1], 8)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [False] * 7 + [True])
        self.assertEqual(TeamSubmission.objects.count(), 1)

    def test_submissions_racing_with_close_are_all_or_nothing(self):
        teams = [join(self.session, f"T{i}")[0] for i in range(8)]
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        q = current_question(self.session)
        s = refresh(self.session)

        def work(i):
            if i == 8:
                return engine.perform(s.pk, self.host, "close_question", expected_status="QUESTION_OPEN", expected_runtime=s.current_runtime_id)
            return services.submit_answer(teams[i], s.current_runtime_id, correct_answer(q))

        results, errors = run_threads(work, 9)
        accepted = TeamSubmission.objects.count()
        self.assertEqual(accepted + len(errors), 8)
        self.assertTrue(all(e.code == "QUESTION_CLOSED" for e in errors))
        rt = refresh(self.session).current_runtime
        self.assertTrue(all(sub.submitted_at <= rt.closed_at for sub in rt.submissions.all()))

    def test_double_clicked_host_action_applies_once(self):
        join(self.session, "Vector")
        results, errors = run_threads(
            lambda i: engine.perform(self.session.pk, self.host, "start_game", expected_status="LOBBY", expected_runtime=None), 5
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 4)
        self.assertEqual(refresh(self.session).events.filter(kind="start_game").count(), 1)

    def test_concurrent_reveals_award_once(self):
        team, _ = join(self.session, "Vector")
        act(self.session, self.host, "start_game")
        act(self.session, self.host, "start_question")
        q = current_question(self.session)
        services.submit_answer(team, refresh(self.session).current_runtime_id, correct_answer(q))
        act(self.session, self.host, "close_question")
        s = refresh(self.session)
        run_threads(lambda i: engine.perform(s.pk, self.host, "reveal_answer", expected_status="QUESTION_CLOSED", expected_runtime=s.current_runtime_id), 5)
        self.assertEqual(ScoreEvent.objects.filter(team=team).count(), 1)
