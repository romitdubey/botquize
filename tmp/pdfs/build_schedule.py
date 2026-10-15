from datetime import date,timedelta
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from pypdf import PdfReader
P='output/pdf/csir_life_science_revision_schedule.pdf'
groups=[
('Biochemistry','Introduction to Biochemistry; Discoveries in Biochemistry',3,22),
('Biochemistry','Digestion; Bioenergetics; Biological Oxidation and Reduction',23,45),
('Biochemistry','Enzymes and Coenzymes; Enzyme kinetics',46,68),
('Biochemistry','Carbohydrate Metabolism; Lipid Metabolism',69,91),
('Biochemistry','Amino Acid and Protein Metabolism; Nucleic Acid & Nucleotide Metabolism and the Urea Cycle; Porphyrin Metabolism',92,111),
('Biochemistry','Citric Acid Cycle; Vitamins and Minerals',112,126),
('Biochemistry','Electron Transport & Oxidative Phosphorylation; Pentose Phosphate Pathway; Photosynthesis - Light and Dark Reactions',127,141),
('Biochemistry','Signal Transduction; Biochemical Pathway Interconnections',142,153),
('Cell Biology','Cellular Organization; Cell Divisions',164,190),
('Cell Biology','Cell Cycle; Cell Organelles',191,207),
('Cell Biology','Cytoskeleton',208,218),
('Cell Biology','Cell Signaling and Communication',219,231),
('Developmental Biology','Gametes and Gametogenesis',236,255),
('Developmental Biology','Fertilization and Zygote Formation; Early Development and Germ Layers',256,270),
('Developmental Biology','Organogenesis - first half',271,283),
('Developmental Biology','Organogenesis - second half; Sex Determination',284,300),
('Genetics & Molecular Biology','Discoveries in Genetics and Molecular Biology',304,324),
('Genetics & Molecular Biology','Mendelian and Non-Mendelian Inheritances',325,336),
('Genetics & Molecular Biology','Nucleic Acids; DNA Replication',337,362),
('Genetics & Molecular Biology','RNA Transcription; Central Dogma - Genetic Code/Translation',363,380),
('Genetics & Molecular Biology','DNA Condensation and Structural Organization; Prokaryotic Genetics',381,395),
('Genetics & Molecular Biology','Regulation of Gene Expression; Mutations and DNA Repair Mechanisms',396,411),
('Genetics & Molecular Biology','rDNA and Genetic Engineering',412,424),
('Immunology','Introduction; History; Innate Immune System; Adaptive Immune System',431,452),
('Immunology','Antigens; Immunoglobulins; Antigen-Antibody Interactions; Humoral Immune Mechanisms',453,473),
('Immunology','Cell Mediated Immune Mechanisms; Immunoglobulin Genes; Major Histocompatibility Complex; Antigen Processing and Presentation',474,488),
('Immunology','B Cell and T Cell Development; Cytokines; Complement System',489,503),
('Immunology','Hypersensitive Reactions; Vaccines; Autoimmunity',504,520),
('Immunology','Immunodeficiency; Hematopoiesis; Transplantation Immunology; Antibody Engineering',521,533),
('Immunology','Experimental Immunology/Immunotechniques; Immunological Discoveries',534,554),
]
start=date(2026,10,16); end=date(2026,12,10)
study_dates=[]; d=start
while len(study_dates)<len(groups):
 if d.weekday()<5: study_dates.append(d)
 d+=timedelta(days=1)
assert study_dates[-1]==date(2026,11,26)
study=dict(zip(study_dates,groups))
revision={date(2026,11,27):'Biochemistry recall: enzymes, energetics and central metabolic pathways',date(2026,11,30):'Biochemistry integration + Cell Biology recall: pathway links, organelles, cycle and signaling',date(2026,12,1):'Developmental Biology recall: gametes, fertilization, germ layers, organogenesis and sex determination',date(2026,12,2):'Genetics recall: inheritance, nucleic acids, replication, transcription and translation',date(2026,12,3):'Genetics recall: chromatin, gene regulation, repair and genetic engineering',date(2026,12,4):'Immunology recall: innate/adaptive, antibodies, antigen presentation and lymphocyte development',date(2026,12,7):'Immunology recall: complement, hypersensitivity, vaccines, clinical topics and methods',date(2026,12,8):'Mixed revision: weakest two topics from PYQs/mocks + recurring wrong questions',date(2026,12,9):'All five parts: closed-book diagrams, comparison tables and experimental interpretation',date(2026,12,10):'Final closure: due re-tests, remaining flagged questions and one-page summaries; no new chapter'}
styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name='TitleX',fontName='Helvetica-Bold',fontSize=27,leading=32,textColor=colors.HexColor('#12354b'),spaceAfter=18)); styles.add(ParagraphStyle(name='SmallX',fontSize=9,leading=13)); styles.add(ParagraphStyle(name='CellX',fontSize=9,leading=12)); styles.add(ParagraphStyle(name='HeadX',fontName='Helvetica-Bold',fontSize=16,leading=20,textColor=colors.HexColor('#12354b'),spaceAfter=12)); styles['BodyText'].leading=15
story=[]
def p(t,sty='BodyText'): return Paragraph(t,styles[sty])
def add(t,sty='BodyText'): story.extend([p(t,sty),Spacer(1,10)])
def table(rows,widths):
 t=Table([[p(str(c),'CellX') for c in row] for row in rows],colWidths=widths,hAlign='LEFT'); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dcecf1')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),('LINEBELOW',(0,0),(-1,-1),.35,colors.HexColor('#cbd5dc'))]));story.append(t)
add('CSIR NET Life Science<br/>Study + Quiz Planner','TitleX'); add('16 October - 10 December 2026','HeadX')
add('A topic-wise revision plan for the five book sections in your uploaded contents pages. Weekday study, next-day Telegram MCQs, Saturday PYQ and Sunday paid mock.')
table([['Milestone','Target'],['First coverage of all 65 listed chapters','26 November'],['Consolidation and mistake revision','27 November - 10 December'],['Scope','30 first-pass weekdays + 10 revision weekdays; 8 Saturdays and 8 Sundays'],['Book workload','529 estimated content pages, excluding answer annexures']],[175,340])
story.append(Spacer(1,16));add('<b>Planning assumptions:</b> Previously studied topics, around 4-5 focused hours on weekdays, starting 16 October. This is an initial plan because daily available hours and question counts are unknown. A fresh start or only 2-3 hours/day needs a lighter or longer plan.')
add('<b>Scope matters:</b> This completes the supplied book contents: Biochemistry, Cell Biology, Developmental Biology, Genetics & Molecular Biology, and Immunology. It does not establish complete coverage of the entire exam syllabus. Match any other syllabus units with her existing preparation separately.')
add('<b>Exam date:</b> 15 December is your planning assumption, not a verified examination date here. The official December 2026 application page was checked on 15 October; that page did not specify the Life Science examination date. Keep the 10 December target and check the official notice/admit card.', 'SmallX')
add('Official reference: <link href="https://csirnet.nta.nic.in/online-application-for-joint-csir-ugc-net-december-2026-is-live/" color="#136c83">NTA December 2026 application announcement</link>', 'SmallX')
story.append(PageBreak())
add('How to run each day','TitleX')
for t in [
'<b>Weekday rhythm:</b> 20 minutes closed-book recall; 60-90 minutes for yesterday\'s MCQs; 120-150 minutes for today\'s concepts and book coverage; 30-45 minutes checking mistakes. Shift actual times to her routine.',
'<b>All book questions:</b> Upload every question from the assigned printed page range, using the relevant answer annexure to verify the key. Question counts are not visible in the contents, so the page load is only a rough estimate. Keep chapter text, images and original question numbers together.',
'<b>MCQ timing:</b> Today\'s study is quizzed tomorrow, including Friday study on Saturday. Monday has no new Sunday-study quiz: use its quiz slot for old mistakes or backlog. On the very first day use a short baseline instead.',
'<b>Saturday:</b> First finish Friday\'s book quiz, then one full PYQ paper in the applicable official time limit. Review errors and guesses the same day. If the book quiz is large, split it before/after the PYQ and use Monday\'s catch-up slot; record the outstanding count.',
'<b>Sunday:</b> One paid mock in exam conditions, followed by analysis. Log the three biggest weaknesses and choose two for Monday. No new book topic is assigned on weekends.',
'<b>Spaced retrieval:</b> Revisit mistakes after 2 days and after 7 days for 10-15 minutes within the recall slot. An answer guessed correctly still enters the error log.',
'<b>Overload rule:</b> After the first two batches, use actual minutes per question to estimate the next day\'s load. If a quiz needs over 90 minutes, split into labelled batches, track every question, and use the next catch-up slot. Never mark a topic complete until all questions and explanations are checked.',
'<b>Recovery:</b> One missed weekday: use the next Monday catch-up slot or 27 November first. More than two missed weekdays, or a persistent quiz backlog, means the plan needs rebalancing; do not silently drop chapters or assume every question will fit.',
'<b>Notes workflow:</b> Send the topic pages before its study date. Notes should contain a concept map, key mechanisms, comparison tables, diagrams, experimental reasoning and common traps. These contents images alone are not sufficient to produce book-faithful notes.',
'<b>Page convention:</b> All page numbers are printed book pages, inferred from the next chapter start. Answer annexures: Biochemistry starts 154; Cell Biology 232; Developmental Biology 301; Genetics 425; Immunology 555. These annexures are for answer checking, not new study load.',
'<b>Small-topic exception:</b> A few days bundle 3-4 very short related chapters to leave genuine revision time. Organogenesis is split across two days; adjust its split at a natural subheading.'
]: add(t,'SmallX')
story.append(PageBreak())
week=date(2026,10,12); wi=0
while week<=end:
 wi+=1; add(f'Week {wi} | {week.strftime("%d %b")} - {(week+timedelta(days=6)).strftime("%d %b %Y")}','HeadX')
 rows=[['Date','Study / main task','Telegram quiz / follow-through']]
 for off in range(7):
  day=week+timedelta(days=off)
  if day<start or day>end:continue
  prev=day-timedelta(days=1)
  if day in study:
   part,title,a,b=study[day]; main=f'<b>{part}</b><br/>{title}<br/><b>pp. {a}-{b} | {b-a+1} pages</b>'
  elif day.weekday()==5: main='<b>Full PYQ test</b><br/>Use a different available paper each week. Analyse wrong, guessed and skipped questions.'
  elif day.weekday()==6: main='<b>Paid full mock</b><br/>Analyse the result; select next week\'s two weakest areas.'
  else: main='<b>Revision / recall</b><br/>'+revision[day]
  if prev in study:
   _,_,a,b=study[prev];quiz=f'All book MCQs from pp. {a}-{b}. Check key + log errors.'
  elif prev in revision: quiz='Re-test yesterday\'s weak concepts / flagged questions; check explanations.'
  elif day==start:quiz='Baseline: short mixed recall check. Prepare tomorrow\'s first book quiz.'
  elif day.weekday()==0:quiz='Catch-up: unfinished book MCQs first, then last week\'s wrong/guessed questions.'
  elif day.weekday()==6:quiz='No new book quiz. Carry forward Friday backlog only if any; protect mock analysis.'
  else:quiz='Short mixed error-log quiz; clear outstanding questions.'
  rows.append([day.strftime('%a<br/>%d %b'),main,quiz])
 table(rows,[58,280,177]);story.append(Spacer(1,14))
 if week<date(2026,12,7):add('Daily check: [ ] concepts recalled   [ ] all assigned MCQs attempted   [ ] explanations checked   [ ] errors logged','SmallX')
 else:
  add('<b>10 December closure:</b> All 65 chapters covered, all assigned book MCQs accounted for, weak-topic re-tests checked. The 9 December quiz closes on 10 December; use 10 December for closure rather than adding a new batch.','SmallX')
  add('<b>11 December until the actual exam:</b> Light recall, diagrams, formulas and existing error log. Keep sleep regular. Avoid new heavy material. Set the final taper dates after checking the official examination schedule.','SmallX')
 story.append(PageBreak());week+=timedelta(days=7)
add('Progress tracker & handover','TitleX')
add('Use this weekly record beside Telegram. Accuracy alone is not completion: keep total, attempted, wrong and remaining counts. These are manual tracking fields; this PDF does not change the bot.')
rows=[['Week ending','Book Qs total / done / left','PYQ score + weak areas','Mock score + weak areas']]
for i in range(8):rows.append([(date(2026,10,18)+timedelta(days=7*i)).strftime('%d %b'),'Total: ____<br/>Done: ____<br/>Left: ____','Score: ____<br/>Weak: __________<br/>________________','Score: ____<br/>Weak: __________<br/>________________'])
table(rows,[75,125,145,170]);story.append(Spacer(1,13))
add('<b>Topic completion:</b> Read/recalled + every question attempted + key/explanation checked + wrong/guessed questions re-tested. Suggested planning signal: below 60% accuracy = priority repair; 60-79% = targeted practice; 80%+ = maintain with recall. These are study triage bands, not exam cut-offs.','SmallX')
add('<b>Bot limitation:</b> The current app loses history on a restart and shares answers between authorized users. Keep this manual record until persistence and separate learner tracking are implemented.','SmallX')
def footer(canvas,doc):
 canvas.setStrokeColor(colors.HexColor('#cbd5dc'));canvas.line(40,37,555,37);canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#536674'));canvas.drawString(40,25,'Life Science | Book-based revision | 16 Oct - 10 Dec 2026');canvas.drawRightString(555,25,str(doc.page))
SimpleDocTemplate(P,pagesize=(595.28,841.89),rightMargin=40,leftMargin=40,topMargin=38,bottomMargin=48).build(story,onFirstPage=footer,onLaterPages=footer)
r=PdfReader(P);print('PDF pages:',len(r.pages));print('Study days:',len(study));print('Content pages:',sum(b-a+1 for _,_,a,b in groups));print('Revision days:',len(revision))
assert sum(b-a+1 for _,_,a,b in groups)==529
assert len(r.pages)==12
