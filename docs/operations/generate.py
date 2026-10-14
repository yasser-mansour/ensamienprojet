"""Documentation-only generator. Run with bundled Python; no Django/database imports."""
from pathlib import Path
import json,re,hashlib,html,unicodedata
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Table,TableStyle
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader,PdfWriter
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).resolve().parent; OUT=HERE/'deliverables'; OUT.mkdir(exist_ok=True)
SOURCE=HERE/'source'; FONT='/System/Library/Fonts/Supplemental/'
pdfmetrics.registerFont(TTFont('Lab',FONT+'Arial.ttf')); pdfmetrics.registerFont(TTFont('LabBold',FONT+'Arial Bold.ttf'))
pdfmetrics.registerFontFamily('Lab',normal='Lab',bold='LabBold',italic='Lab',boldItalic='LabBold')
styles=getSampleStyleSheet()
for s in styles.byName.values(): s.fontName='Lab'; s.leading=14
styles['Title'].fontName='LabBold'; styles['Title'].textColor=colors.HexColor('#163544')
styles['Heading1'].fontName='LabBold'; styles['Heading2'].fontName='LabBold'
styles.add(ParagraphStyle(name='SmallLab',fontName='Lab',fontSize=8,leading=11))
styles['BodyText'].fontSize=10; styles['BodyText'].spaceAfter=7

def clean(s):
 return str(s).replace('→',' -> ').replace('–','-').replace('—','-').replace('↑',' increases ').replace('↓',' decreases ').replace('\x7f','-').replace('≈','about ').replace('≤','<=')
def para(s,style='BodyText'): return Paragraph(html.escape(clean(s)).replace('\n','<br/>'),styles[style])
def page(title,lines): return [para(title,'Heading1')]+[para(x) for x in lines]
def footer(c,d):
 c.setFont('Lab',8); c.setFillColor(colors.HexColor('#45535c')); c.drawString(42,813,'ENERGY LAB | CRASH TEST #05 | OPERATIONS'); c.drawString(42,25,'Nine presenters | Source-backed plan | 14 October 2026'); c.drawRightString(553,25,str(d.page))
def pdf(path,pages):
 story=[]
 for i,p in enumerate(pages):
  if i: story.append(PageBreak())
  story.extend(p)
 SimpleDocTemplate(str(path),pagesize=(595.28,841.89),leftMargin=42,rightMargin=42,topMargin=48,bottomMargin=45).build(story,onFirstPage=footer,onLaterPages=footer)
with ZipFile(SOURCE/'ENERGY_LAB_UNIT5.pptx') as z:
 slides=[]
 for i in range(1,89):
  def txt(name): return '\n'.join(n.text or '' for n in ET.fromstring(z.read(name)).iter() if n.tag.endswith('}t'))
  slides.append(dict(number=i,text=txt(f'ppt/slides/slide{i}.xml'),notes=txt(f'ppt/notesSlides/notesSlide{i}.xml')))
missions=json.loads((ROOT/'fixtures/energy_lab.json').read_text())['missions']
# Nine-person operational assignments are a new documented plan, not recovered Claude data.
segments=[(0,5,'Cold open',1,5,1),(5,12,'Potential and kinetic energy',6,10,2),(12,18,'Mission 01: Energy Scan',11,20,2),(18,24,'Vocabulary: dynamics',21,26,3),(24,30,'Vocabulary: research',27,30,4),(30,39,'Mission 02: Vocabulary Battle',31,32,4),(39,42,'Crash alert',33,34,1),(42,56,'Seatbelt investigation',35,40,5),(56,63,'Mission 03: Crash Detective',41,55,5),(63,76,'Language of engineers',56,61,6),(76,82,'Mission 04: Error 404',62,72,6),(82,90,'Listening',73,77,7),(90,98,'Design pitch',78,81,7),(98,102,'Writing',82,83,8),(102,104,'Mission 05: Final Crash Simulation',84,86,9),(104,105,'Certification and close',87,88,1)]
roles={1:('Team captain / mission commander','Opening, crash alert, final synthesis; protect teaching and approve fallback decisions.'),2:('Energy engineer','Teach energy; lead Mission 01; explain physical examples.'),3:('Dynamics engineer / timekeeper','Teach slides 21-26; track the segment clock; collect mentor scores.'),4:('Research engineer','Teach slides 27-30; lead Mission 02; explain matching and vocabulary.'),5:('Crash investigator','Lead reading and Mission 03; distinguish quoted text from supplementary science.'),6:('Communication engineer','Teach five language patterns; lead Mission 04; validate oral repairs.'),7:('Testing and speaking engineer','Lead listening and pitches; manage two listening passes and 45-second presentations.'),8:('Writing engineer / floor coordinator','Lead report task; distribute materials; coordinate zone mentors and participation.'),9:('Technical co-pilot / final simulation lead','Operate host and projector; lead final sequence explanation while P3 briefly operates the host.')}
zones={1:'No fixed zone: captain at front',2:'Alpha',3:'Bravo',4:'Charlie',5:'Delta',6:'Echo',7:'Foxtrot',8:'Golf and Hotel',9:'No fixed zone: laptop station'}
support={1:'P8 handles the room; P3 sends a two-minute warning. Do not troubleshoot phones while narrating.',2:'After your mission, mentor Alpha; help P5 explain force reduction and review one design pitch.',3:'Keep the master clock throughout. Mentor Bravo, record offline EP, and cover host clicks only for the final mission.',4:'Mentor Charlie after vocabulary; prepare P7 Task 7 gap answers and read Engineer 1 if audio fails.',5:'Mentor Delta; supply science clarification during reading; review design reasoning with P7.',6:'Mentor Echo; read Engineer 2 with P4 if audio fails; check comparatives/future forms in pitches and reports.',7:'Mentor Foxtrot outside your teaching block; announce pitch speakers; keep audio and speaking within eight minutes each.',8:'Coordinate all eight companies; directly mentor Golf and Hotel with rotating help from the idle teaching presenters. Collect report drafts and log participation evidence.',9:'Monitor connectivity and projected state; execute the five host missions; keep offline score totals separate. Teach final cards at 102 minutes while P3 controls the host.'}
prep={1:'Rehearse the ball demonstration safely, the 33-34 narrative bridge, and a 60-second closing. Check all nine attendance and handoff readiness.',2:'Rehearse each of the five situations, including the ramp sequence; explain potential energy as position/configuration rather than just being still.',3:'Practise decelerate, stopping distance, force and work examples. Practise host CLOSE/REVEAL/NEXT for the final under P9 supervision.',4:'Learn Task 4 matches (1-A, 2-D, 3-C, 4-B). Rehearse the actual app matching question; compare it with the local quiz bank without changing application content.',5:'Read slides 35-40 and all seven statements. Separate literal reading answers from standard-physics clarification. Rehearse a three-minute reading window.',6:'Explain can + base verb, comparative -er, be going to, future present continuous and passive. Practise five fixes and the Engineer 2 dialogue.',7:'Test available official audio. Prepare the live dialogue with P4/P6; leave gap 5 ungraded unless verified. Practise selecting two pitches after four minutes of preparation.',8:'Count 90 handouts (or 45 shared copies), make eight company signs, and prepare an EP ledger. Rehearse a four-minute report-start task rather than demanding a completed 120-word report.',9:'Rehearse host state transitions, PAUSE/RESUME, projector reopen, recovery code, manual adjustment with reason, and final B-D-A-C. Verify deployed content against this source snapshot before class.'}
owner={i:p for a,b,name,lo,hi,p in segments for i in range(lo,hi+1)}
intro=page('ENERGY LAB - Nine Presenter Operations Manual',[
'105-minute English engineering lesson | ENSAM Meknes | about 90 classmates | eight companies Alpha-Hotel.',
'P1 is the team captain. P9 is the technical co-pilot. This plan assigns teaching, assessment, room support, preparation and contingency duties to all nine people.',
'Recovery status: the local folder was not a Git repository. GitHub repository yasser-mansour/ensamienprojet was recovered at commit 306eb20 on claude/ensamien-classroom-platform-cl7v5e. No 105-page manual, manual dataset, generator or manual QA script exists in its available history. This is a replacement documentation pipeline because those sources are genuinely absent.',
'Preserved materials: 88-slide PPTX with all 88 notes; 12-page eight-presenter guide; 2-page student dossier; local quiz and listening fallback; application source and fixture. Original files and application logic are unchanged.',
'Validation scope: slide ownership and mission content verified against supplied files and application source. Deployed database content, actual room equipment and official listening audio are not verified. Run the classroom acceptance checklist before delivery.',
'Navigation: timeline and role map; slide registry; host operations; five mission runbooks; contingency and rehearsal; nine dossiers, each ending with a one-page card. Presenter PDFs are exact extracts of dossier pages.'])
pages=[intro]
pages.append(page('Team structure and workload',[
'Captain: P1 owns decisions, narrative and timing escalation. Technical co-pilot: P9 owns devices and host actions. P3 tracks time and is trained as the temporary host backup. P8 coordinates the floor. These roles avoid putting both narration and troubleshooting on P1.',
'Eight companies: distribute 90 students as two groups of 12 and six groups of 11. One phone captain submits per company; everyone discusses before submission. Rotate speaker, reader and recorder so the phone captain does not dominate.',
'Room plan: projector at front, P9 at laptop with direct sight of screen, P1 at front. Place Alpha-Bravo / Charlie-Delta / Echo-Foxtrot / Golf-Hotel in paired zones with clear aisles. P8 covers Golf/Hotel; idle presenters help there when P8 teaches. Confirm the actual room layout before class.',
'Work is allocated by learning and operating goals, not equal microphone time. P8 has a short writing block but manages materials and assessment across the lesson. P9 operates every mission and teaches the final; P3 covers those final clicks.',
'Active speaker stays at the front; idle teaching presenters circulate. During their own speaking turn, a mentor delegates their company check to P8 or the nearest idle presenter. During listening all mentors stay quiet.',
]+[f'P{i}: {roles[i][0]}. {roles[i][1]} Zone: {zones[i]}.' for i in roles]))
def stamp(n):return f'{n//60:02d}:{n%60:02d}'
time_lines=[f'{stamp(a)}-{stamp(b)} | {b-a} min | slides {lo}-{hi} | P{p} | {name}' for a,b,name,lo,hi,p in segments]
pages.append(page('Master timeline - 105 minutes',time_lines+[
'Every handoff and screen change is included in its block. P3 gives a quiet two-minute warning and records actual end times. P1 decides reductions: shorten explanations and select two pitches, retain all learning stages.',
'The older guide labels reading as slides 35-55; actual reading is 35-40 and Crash Detective is 41-55. Likewise language teaching is 56-61, Error 404 is 62-72. This timeline corrects those boundaries.',
'The last three minutes split into a two-minute final mission (P9) and one-minute closing (P1). Four writing minutes start an outline/draft; finish the 100-120-word report after class. Do not claim all students can finish it in four minutes.']))
hand_lines=[]
for idx,s in enumerate(segments[:-1]):
 a,b,name,lo,hi,p=s; nxt=segments[idx+1]; np=nxt[-1]
 hand_lines.append(f'At {stamp(b)}, slide {hi} -> {nxt[3]}: P{p} says "{name} complete. Next, {nxt[2].lower()}. P{np}, take over." P{np} acknowledges; P9 restores the deck or opens the required mission intro. P3 confirms time.')
pages.append(page('Explicit handoffs and display cues',hand_lines[:8]))
pages.append(page('Explicit handoffs - continued',hand_lines[8:]+['Within a speaker block, use the existing PPTX TRANSITION notes. The new ownership registry overrides old P1-P8 labels; keep the original deck unchanged.', 'Mission mode: project the app instead of duplicate deck question/answer slides. Those slides remain owned by the mission lead for offline fallback. Never reveal a deck answer before app submissions close.']))
for start in range(1,89,16):
 lines=[]
 for s in slides[start-1:start+15]:
  meaningful=[t for t in s['text'].splitlines() if t.strip() and not t.isdigit() and 'ENERGY LAB' not in t]
  lines.append(f"Slide {s['number']:02d} | owner P{owner[s['number']]} | "+' / '.join(meaningful[:3]))
 pages.append(page(f'Actual slide registry - {start}-{min(start+15,88)}',lines))
pages.append(page('ENSAMien LIVE - host operating procedure',[
'Source: docs/REHEARSAL.md, templates/live/host_control.html, live/engine.py and live/services.py. Verify the deployed build before class; this manual describes recovered commit 306eb20.',
'Before class: P9 signs in at /host/login/, creates a NEW rehearsal/session as appropriate, and opens the projector via OPEN PROJECTOR. Press F on the display for full screen. Keep the host dashboard on the private laptop screen so answer keys are not projected.',
'P8 helps eight captains join using the displayed site/QR and session code. QR opens the site; captains still enter the code. Check all eight company names before START GAME, which closes registration.',
'First mission: START GAME -> mission intro -> START QUESTION -> CLOSE QUESTION -> REVEAL ANSWER. Explain the result, then NEXT QUESTION; next_question directly opens the next question. After the last question it enters MISSION COMPLETE. SHOW LEADERBOARD at the boundary, then NEXT MISSION when the next teaching block reaches its mission.',
'Timer zero does not reveal automatically. Submissions are checked against the server deadline; close explicitly, then reveal. +15 s is available while a question is open; REOPEN (15 s) is available when closed. PAUSE freezes the timer; RESUME restores it.',
'Do not advance NEXT MISSION during teaching. Leave a stable leaderboard or mission-complete state, switch to PPTX, and return to the host at the next mission cue. P9 owns window switching.',
'Manual EP: team menu -> score amount -> meaningful reason -> Apply score change. Speaking/writing are not auto-scored. P8 supplies evidence; P9 enters it once. Restart keeps awarded points and does not award a scored question twice; it is not a score reset.',
'Final mission: P3 performs host clicks while P9 teaches. After the answer and leaderboard, FINISH GAME displays final results. Do not archive until the report is saved/reviewed. No deployment, migrations or content reseeding are part of this task.']))
pages.append(page('Content differences, scoring and science',[
'App Mission 02 differs from quiz_questions.md because that bank was unavailable during the application build. Use the fixture-derived question sheets in this manual for the live session and for its offline continuation. Do not silently alternate question sets mid-mission.',
'App correct-answer points: normally 100 EP, final ORDER question 300 EP. The older deck says double EP. For this app-backed plan announce 300 EP for the final and explain that the deck scoring label belongs to its earlier offline version. No business logic changes are needed.',
'For a comparable paper fallback, use 100 EP per correct full answer and 300 EP for the final. Matching is all-or-nothing in the app. Keep speed bonus OFF for the simplest paper-compatible scoring; verify its setting before START GAME. Manual participation awards are separate and documented.',
'Science clarification, supplementary: passengers in a moving car already have kinetic energy relative to the road. A crash does not generally convert stored potential energy into their motion. The textbook wording is retained only when assessing its literal reading; label the physics clarification explicitly.',
'Science clarification, supplementary: the work-energy theorem relates net work to change in kinetic energy, not energy equalling distance. For comparable stopping conditions, a longer stopping distance can reduce average stopping force. G is an acceleration ratio rather than an SI unit of force.',
'Official textbook pp.12-13 and official audio were not supplied. Textbook labels in this manual trace to the supplied guide/deck or app fixture, not independent verification of the book. Task 7 gap 5 remains unverified and must not be graded as a confirmed official answer.',
'App question pages that follow reproduce the recovered fixture, including its source labels, answers, timings and science notes. They are private presenter preparation sheets.']))
mission_leads=[2,4,5,6,9]; mission_ranges=[(11,20),(31,32),(41,55),(62,72),(84,86)]; mission_budgets=[6,9,7,6,2]
for m,lead,rng,budget in zip(missions,mission_leads,mission_ranges,mission_budgets):
 seconds=sum(q.get('duration') or m['default_duration'] for q in m['questions'])
 pages.append(page(f"Mission {m['code']} - {m['title']} runbook",[
 f"Lead P{lead}; host P{'3' if lead==9 else '9'}; floor P8; clock P3 (P1 during final). Deck fallback slides {rng[0]}-{rng[1]}. Budget {budget} min; {len(m['questions'])} questions; configured answer timers total {seconds}s. Remaining time covers instructions, state changes, explanations and handoff.",
 m['objective'], m['briefing'],
 'Entry: lead explains response format and asks captains to wait for the open question. Host confirms mission code before starting. Floor checks phones face the team and everyone discusses.',
 'Question cycle: read the prompt; open; wait for submitted/received indicators; close; reveal; give one reason; next. For matching, pair every item before submitting; for ordering, tap cards in order (or drag), using arrows/remove to fix the order.',
 'Exit: verify every planned question was revealed or an explicitly logged skip occurred. Display the mission leaderboard; P8 notes any unresolved device issue. Return to the deck and follow the next handoff.',
 'Offline: P1 announces the switch; P3 records paper EP, P8 collects a single company response, mission lead reads the SAME fixture questions below. Use A/B/C cards for singles, written pairs for matching and written B-D-A-C for the final. Do not add paper points again for already-scored app questions.',
 'Rehearsal acceptance: complete this mission inside its block on real devices, including explanations. If over time, shorten commentary before class; do not rely on skipping required questions on the day.']))
 # Two questions per page, preserving complete source data.
 for k in range(0,len(m['questions']),2):
  block=[]
  for j,q in enumerate(m['questions'][k:k+2],start=k+1):
   block+= [f"Q{j} | {q['kind']} | {q.get('duration') or m['default_duration']} s | {q.get('points',100)} EP",q.get('context',''),q['prompt']]
   block += [f"Item {it['key']}: {it['text']}" for it in q.get('items',[])]
   block += [f'{chr(65+n)}) {opt}' for n,opt in enumerate(q['options'])]
   block += [f"Answer: {q['answer_display']} | key {json.dumps(q['answer_key'])}",q['explanation']]
   if q.get('clarification'):block.append('Science note - supplementary: '+q['clarification'])
   block.append(f"Source: {q['source']} | {q['source_reference']}")
  pages.append(page(f"Mission {m['code']} - private answer sheet {k+1}-{min(k+2,len(m['questions']))}",block))
pages.append(page('Listening, speaking and writing',[
'Listening 82-90 min, slides 73-77: P7 introduces gist listening, plays the official recording once for Task 6, then again for Task 7 writing. If missing, P4 reads Engineer 1 and P6 Engineer 2 using source/listening_fallback.md. State that this is a live reading, not official audio. P9 handles playback/window switching.',
'Task 6 answers: B (benefits of a new seatbelt design), D (safer than current seatbelts). Task 7: 1 safer than; 2 stopping distance; 3 kinetic energy; 4 belt; 5 unverified audio-only phrase; 6 testing. Accept no graded official answer for gap 5 without audio/key confirmation.',
'Speaking 90-98 min, slides 78-81: P7 gives instructions (1 min), companies prepare (4 min), two companies pitch for 45 seconds each plus brief feedback and selection (3 min). P8 rotates who speaks; mentors check non-selected companies and collect their notes.',
'Pitch checklist: stopping distance, kinetic energy, transfer, force, one comparative, one future form; ask "Why is your design safer?" P5 checks reasoning; P6 checks language. P8 records participation; P9 may enter a consistent +100 speaking-participation award for each company that meets the checklist, with a reason.',
'Writing 98-102 min, slides 82-83: P8 introduces Design / Energy / Safety, asks companies to begin an outline/draft, and collects progress. The completed 100-120-word report is post-class work; four minutes is insufficient for all 90 students to compose, assess and revise it.',
'Private preparation: use the older guide model answer only after submission, never before students write. Assess unit vocabulary, causal reasoning, language form and word count; identify any textbook simplification as a reading claim rather than standard physics.']))
pages.append(page('Emergency procedures and decision owners',[
'Internet failure: P9 checks whether host/display are merely reconnecting. P1 sets a 30-second troubleshooting limit. If service does not recover, P1 calls paper mode; P8 distributes cards and P3 starts an EP ledger. Continue from the next unscored question with fixture sheets.',
'Phone failure: P8 helps the captain refresh. If the device is lost, P9 issues a recovery code from team menu; on a replacement phone enter the session code then Reconnect an existing team. Host UI states code valid ten minutes and once. Avoid creating a duplicate team.',
'Projector browser closed: P9 uses OPEN PROJECTOR again. If PPTX fails, use original ENERGY_LAB_UNIT5.pdf from the supplied workspace; if projection fails entirely, P8 distributes student dossiers and leads paper responses while speakers read concise prompts.',
'Audio failure: P7 calls the live reading; P4 and P6 read their rehearsed parts twice. Keep the unverified fifth gap ungraded. Do not spend the whole block trying to fix sound.',
'Host unavailable: P3 takes the private host station using the existing authorized session; P1 covers clock cues. P9 returns only after an explicit handoff. Do not share host credentials with student captains.',
'Presenter absent: P1 reassigns from the dossier and note sheets. P2 covers P3 vocabulary, P4 covers P5 reading, P6 covers P7 teaching, P8 covers P4 mission narration; P3 covers P9 operations. P1 and P8 resolve room cover before opening.',
'Running late: P3 alerts P1; shorten repeated explanations and take only two pitches. Protect the required reading/listening stages and final explanation. Use the already-declared report continuation after class rather than inventing extra time.',
'Disputed scoring: P8 records team, question and evidence; P9 checks the report and makes one logged manual correction with a reason if warranted. Never announce an unverified winner or restart a mission to erase points.',
'Physical incident: stop the activity, keep aisles clear and follow ENSAM classroom instructions. Use only a safe ball drop/roll; never perform a crash or load test on a person.']))
checklist=[
'Before first rehearsal: all nine read their assigned notes and dossier; P1 confirms role coverage; P9 checks deployed fixture matches the 26-question source snapshot.',
'Content rehearsal: each lead explains answers without reading verbatim; practise textbook-versus-science clarification and the five grammar repairs; verify official audio gap 5 or mark it ungraded.',
'Handoff rehearsal: practise all 15 timed transitions; P9 switches app/deck without exposing the private host; P3 rehearses final host coverage while P9 speaks.',
'Full timed rehearsal: 88-slide route, all five app missions, eight companies/phones; record each segment end and total <=105 min. Include four-minute pitch preparation and report-start block.',
'Technical rehearsal: scan QR from the back row, join eight teams, confirm code entry, close/reveal manually at timer zero, pause/resume, refresh, reconnect, issue recovery code and reopen projector.',
'Failure rehearsal: no Wi-Fi, lost phone, failed audio, missing speaker, closed projector window. Check the unscored-question ledger prevents double counting.',
'Day before: charge laptop/phones, confirm adapter and speakers, make eight signs, print 90 dossiers or 45 pair copies, prepare paper EP sheet and A/B/C/D cards; keep deck PDF available.',
'Day of: P8 places zones/handouts; P9 opens the private host and public projector; P3 sets clock; P1 checks nine presenters and calls readiness. Confirm the final is announced as 300 EP.',
'After class: P9 reviews/saves the session report; P8 collects reports/notes; P3 compares actual timing; P1 records improvements. Archive only after report review.']
pages.append(page('Preparation and rehearsal acceptance checklist',checklist))
base_count=len(pages); ranges={}; cards=[]
for i in range(1,10):
 own=[s for s in segments if s[-1]==i]
 duties=[f'{stamp(a)}-{stamp(b)} | {name} | slides {lo}-{hi}' for a,b,name,lo,hi,p in own]
 teaching=page(f'P{i} dossier - {roles[i][0]}',[
 roles[i][1], 'Your front-of-room cues:']+duties+[
 'Across the whole lesson: '+support[i], 'Your zone: '+zones[i],
 'Preparation: '+prep[i],
 'Rehearsal: deliver your assigned segment at its budget, practise the incoming and outgoing handoff, then rehearse your secondary task while another presenter speaks.',
 'Bring: this dossier, assigned speaker notes, a pen and cue timer if applicable. Know where the paper response cards and student dossiers are stored.',
 'Success: students can explain the concept or complete the task; your partner receives a clear handoff; the mission lead and host never compete for the same device.'])
 notes=[]
 for s in slides:
  if owner[s['number']]==i:
   # Full original notes preserved in editable source export; concise cues on PDF.
   fields=re.split(r'(?=OBJECTIVE:|SAY:|ASK:|ACTION:|TRANSITION:|SOURCE:|NOTE:)',s['notes'])
   cue=' '.join(t for t in fields if t.startswith(('OBJECTIVE:','TRANSITION:')))
   notes.append(f"Slide {s['number']}: {cue}")
 dossier=[teaching]
 for j in range(0,len(notes),5):dossier.append(page(f'P{i} - slide cues {j+1}-{min(j+5,len(notes))}',notes[j:j+5]))
 dossier.append(page(f'P{i} - preparation, rehearsal and fallback',[
 'Study: '+prep[i],
 'Partner check: rehearse with P9 for screen cues, P3 for timing and P8 for zone cover. P1 confirms that your secondary duty can continue without distracting from the active speaker.',
 'During missions: follow the fixture-derived private answer sheets. Mentors listen to company discussion, give no answer before CLOSE, and check that one captain submits.',
 'During teaching: circulate quietly, identify one misconception, and feed it to the lead at the next pause. During listening: no side explanations.',
 'On failure: tell P1 what failed and P9 which question is affected. Do not independently restart, reseed, create another session or change scoring. Use the emergency section.',
 'Personal rehearsal acceptance: name your incoming presenter; state your first line; perform the exact screen cue; finish within budget; give the next presenter a named handoff; complete one simulated failure.',
 'After rehearsal: record actual elapsed time and unresolved questions. Confirm the official audio limitation, final 300 EP rule and post-class writing completion with your teammates.']))
 card=page(f'P{i} - one-page quick reference',[
 roles[i][0], 'Primary: '+roles[i][1], 'Cues:']+duties+[
 'Secondary: '+support[i], 'Zone: '+zones[i],
 'Before class: '+prep[i],
 'Handoff: finish one explanation, name the next stage and presenter, wait for acknowledgement. P9 changes the screen; P3 confirms time.',
 'If stuck: ask P1 for the decision, P9 for devices, P8 for the room. At 30 seconds of unresolved connectivity, use the paper fallback on the same unscored question.',
 'Remember: one submitting phone per company; no early answer reveal; Task 7 gap 5 ungraded; final B-D-A-C = 300 EP; writing is a draft now and completed after class.'])
 dossier.append(card); cards.append(card)
 start=len(pages)+1;pages.extend(dossier);ranges[str(i)]=[start,len(pages)]
master=OUT/'ENERGY_LAB_NINE_PRESENTER_OPERATIONS_MANUAL.pdf';pdf(master,pages)
r=PdfReader(master)
# Explicit pages are required to be exactly one physical page each.
assert len(r.pages)==len(pages),(len(r.pages),len(pages),'Unexpected page overflow')
for i,(start,end) in ranges.items():
 w=PdfWriter()
 for p in r.pages[start-1:end]:w.add_page(p)
 with (OUT/f'ENERGY_LAB_PRESENTER_{int(i):02d}.pdf').open('wb') as f:w.write(f)
pdf(OUT/'ENERGY_LAB_QUICK_REFERENCE_CARDS.pdf',cards)
(OUT/'ENERGY_LAB_ROLE_ASSIGNMENTS.md').write_text('# Nine presenter role assignments\n\nNew documentation plan based on recovered sources; P1 captain, P9 technical co-pilot.\n\n'+'\n\n'.join(f'## P{i} - {roles[i][0]}\n\n{roles[i][1]}\n\n{support[i]}\n\nZone: {zones[i]}\n\nPreparation: {prep[i]}' for i in roles)+'\n\n## Every actual slide\n\n'+'\n'.join(f'- Slide {i}: P{owner[i]}' for i in owner))
(OUT/'ENERGY_LAB_MASTER_TIMELINE.md').write_text('# 105-minute timeline\n\n'+'\n'.join('- '+x for x in time_lines)+'\n\n## Handoffs\n\n'+'\n\n'.join(hand_lines)+'\n\nWriting is begun in class and completed after class. Final app mission is 300 EP. During app missions the corresponding PPTX question/answer slides are offline fallback.\n')
(OUT/'ENERGY_LAB_REHEARSAL_CHECKLIST.md').write_text('# Rehearsal checklist\n\n'+'\n\n'.join('- [ ] '+x for x in checklist))
(OUT/'ENERGY_LAB_FULL_MANUAL.md').write_text('\n\n---\n\n'.join('\n\n'.join(re.sub('<[^>]+>','',html.unescape(x.text)) for x in p if isinstance(x,Paragraph)) for p in pages))
(HERE/'slide_source.json').write_text(json.dumps(slides,ensure_ascii=False,indent=2))
manifest={'master_pages':len(r.pages),'presenter_ranges':ranges,'quick_card_master_pages':[v[1] for v in ranges.values()],'slide_count':len(slides),'mission_question_counts':[len(m['questions']) for m in missions],'source_commit':'306eb20','segments':segments,'owners':owner,'sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(SOURCE.iterdir())},'fixture_sha256':hashlib.sha256((ROOT/'fixtures/energy_lab.json').read_bytes()).hexdigest()}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'pages':len(r.pages),'dossiers':ranges,'outputs':str(OUT)}))
