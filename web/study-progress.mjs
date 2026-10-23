// Progress counts scheduled study portions, not whole-unit mastery or test scores.
export const UNIT_NAMES=[
 'Biomolecules','Cellular Organization','Fundamental Processes','Cell Communication and Signaling',
 'Developmental Biology','Plant Physiology','Animal Physiology','Inheritance Biology',
 'Evolution and Diversity','Ecology and Behaviour','Bioinformatics and Computational Biology',
 'Biochemical Engineering and Industrial Biotechnology','Advances in Biotechnology','Methods in Biology',
];
export function studyProgress(schedule,days={}){
 const units=UNIT_NAMES.map((label,i)=>({id:i+1,label:`${i+1}. ${label}`,done:0,total:0}));
 const aptitude={id:'aptitude',label:'Part A · Aptitude',done:0,total:0};
 for(const row of schedule){
  // Preserve credit for the old completed Biochemistry days when the plan changed.
  const parsed=Number(/^Unit (\d+):/.exec(row.part||'')?.[1]);
  const unit=row.unit??(parsed|| (row.part==='Biochemistry'?1:null));
  if(row.kind==='Study'&&Number.isInteger(unit)&&unit>=1&&unit<=14){
   units[unit-1].total++;if(days[row.date]?.studied)units[unit-1].done++;
  }
  if(row.aptitude){aptitude.total++;if(days[row.date]?.aptitude_studied)aptitude.done++;}
 }
 return [...units,aptitude].map(item=>({...item,percent:item.total?Math.round(item.done/item.total*100):0}));
}
