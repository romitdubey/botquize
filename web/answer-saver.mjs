// One request at a time; edits to a waiting question collapse into its newest response.
export class AnswerSaver {
  constructor(write, changed=()=>{}) {this.write=write;this.changed=changed;this.records=new Map();this.running=null;this.closed=false;}
  get pending(){return [...this.records.values()].filter(r=>r.dirty).length;}
  get failed(){return [...this.records.values()].filter(r=>r.dirty&&r.error).length;}
  drafts(){return [...this.records.values()].filter(r=>r.dirty).map(r=>({...r.payload}));}
  notify(){this.changed({pending:this.pending,failed:this.failed,closed:this.closed});}
  set(payload){
    if(this.closed)return;
    const old=this.records.get(payload.index);
    this.records.set(payload.index,{payload:{...payload},revision:(old?.revision||0)+1,dirty:true,error:null});
    this.notify();this.schedule();
  }
  schedule(){
    if(this.running||this.closed)return;
    this.running=Promise.resolve().then(async()=>{
      while(!this.closed){
        const entry=[...this.records.entries()].find(([,r])=>r.dirty&&!r.error);
        if(!entry)break;
        const [index,record]=entry,revision=record.revision;
        try{
          const result=await this.write({...record.payload});
          if(result?.submitted){this.closed=true;this.records.clear();break;}
          const current=this.records.get(index);
          if(current?.revision===revision){current.dirty=false;current.error=null;}
        }catch(error){
          const current=this.records.get(index);
          // An older failed request must never revert or poison a newer answer.
          if(current?.revision===revision)current.error=error;
        }
        this.notify();
      }
    }).finally(()=>{this.running=null;this.notify();});
  }
  async flush(){
    // Retry failed responses explicitly at submit/exit or from Retry sync.
    for(const record of this.records.values())if(record.dirty)record.error=null;
    this.schedule();
    while(this.running)await this.running;
    return this.pending===0;
  }
}
