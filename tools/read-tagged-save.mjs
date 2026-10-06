// Read-only GVAS decoder reused from inspect-game.mjs and inspect-save-properties.mjs.
// Parse this file's own header; never borrow offsets/hashes from another save.
export function saveHeader(b) {
  if (b.toString('ascii',0,4)!=='GVAS') return {magic:b.subarray(0,16).toString('hex'), gvas:false};
  let o=4;
  const i32=()=>{const n=b.readInt32LE(o);o+=4;return n;};
  const u16=()=>{const n=b.readUInt16LE(o);o+=2;return n;};
  const fstring=()=>{
    const n=i32();
    if (Math.abs(n)>100000 || o+Math.abs(n)*(n<0?2:1)>b.length) throw new Error('Invalid FString');
    const size=Math.abs(n)*(n<0?2:1);
    const s=b.toString(n<0?'utf16le':'utf8',o,o+size);
    if(n && !s.endsWith('\0'))throw new Error('FString lacks terminator');
    o+=size;return s.replace(/\0$/,'');
  };
  const saveVersion=i32(), ue4PackageVersion=i32();
  const ue5PackageVersion=saveVersion>=3?i32():null;
  const rawChangelist=b.readUInt32LE(o+6);
  const engine={major:u16(),minor:u16(),patch:u16(),rawChangelist:i32()>>>0,changelist:rawChangelist&0x7fffffff,branch:fstring()};
  const customVersionFormat=i32(), customVersions=[];
  const count=i32();
  if(count<0 || count>10000) throw new Error('Invalid custom-version count');
  for(let i=0;i<count;i++){const guid=b.subarray(o,o+16).toString('hex');o+=16;customVersions.push({guid,version:i32()});}
  const classOffset=o;
  let saveClass;
  try{saveClass=fstring();}catch(e){return {gvas:true,saveVersion,ue4PackageVersion,ue5PackageVersion,engine,customVersionFormat,customVersions,classOffset,classParseError:e.message};}
  return {gvas:true,saveVersion,ue4PackageVersion,ue5PackageVersion,engine,customVersionFormat,customVersions,saveClass,propertyDataOffset:o};
}
export function readTaggedSave(b,name){
 const h=saveHeader(b),schema=[];
 if(!h.gvas||h.ue5PackageVersion!==1018||h.engine.major!==5||h.engine.minor!==7||h.engine.patch!==4||h.engine.changelist!==33649||h.classParseError)throw Error('Unsupported save header');
 const classes={ 'PagodaGP_Main.sav':'/Script/Pagoda.PagodaGlobalProgressSaveGame', 'PagodaPT_M_0.sav':'/Script/Pagoda.PagodaPlaythroughSaveGame' };
 if(h.saveClass!==classes[name])throw Error('Only current global/playthrough progression saves are supported');
 class Reader{
  constructor(p,end=b.length){this.p=p;this.end=end;}
  ensure(n){if(n<0||this.p+n>this.end)throw Error(`Read out of bounds @${this.p}`);}
  i32(){this.ensure(4);const v=b.readInt32LE(this.p);this.p+=4;return v;}
  u8(){this.ensure(1);return b[this.p++];}
  str(){const n=this.i32();if(!n)return '';if(Math.abs(n)>1000000)throw Error('Invalid FString length');this.ensure(Math.abs(n)*(n<0?2:1));const s=b.toString(n<0?'utf16le':'utf8',this.p,this.p+Math.abs(n)*(n<0?2:1));this.p+=Math.abs(n)*(n<0?2:1);if(!s.endsWith('\0'))throw Error('Nonterminated FString');return s.slice(0,-1);}
  type(depth=0){if(depth>20)throw Error('Type recursion limit');const name=this.str(),n=this.i32();if(n<0||n>10)throw Error('Invalid type arity');return {name,args:Array.from({length:n},()=>this.type(depth+1))};}
 }
 const typeText=t=>t.name+(t.args.length?'('+t.args.map(typeText).join(',')+')':'');
 function value(r,t,p,flags=0,depth=0){
  if(depth>25)throw Error('Value recursion limit');
  switch(t.name){
   case 'BoolProperty':return flags===-1?!!r.u8():!!(flags&16);
   case 'IntProperty':return r.i32();
   case 'Int64Property':case 'UInt64Property':r.ensure(8);{const v=b.readBigInt64LE(r.p).toString();r.p+=8;return v;}
   case 'FloatProperty':r.ensure(4);{const v=b.readFloatLE(r.p);r.p+=4;return v;}
   case 'DoubleProperty':r.ensure(8);{const v=b.readDoubleLE(r.p);r.p+=8;return v;}
   case 'NameProperty':case 'StrProperty':case 'EnumProperty':case 'ObjectProperty':return r.str();
   case 'ByteProperty':if(t.args.length)return r.str();return r.u8();
   case 'StructProperty':{
    const st=t.args[0]?.name;
    // GVAS serializes GameplayTag as reflected TagName, not its cooked FName form.
    if(st==='GameplayTag')return properties(r,p,depth+1);
    if(st==='InstancedStruct'){
     const structType=r.str(),size=r.i32();r.ensure(size);const sub=new Reader(r.p,r.p+size);
     const fields=properties(sub,p+'<'+structType+'>',depth+1);if(sub.p!==sub.end)throw Error('InstancedStruct boundary mismatch');r.p+=size;return {structType,fields};
    }
    if(st==='GameplayTagContainer'){const n=r.i32();if(n<0||n>100000)throw Error('Bad tag count');return Array.from({length:n},()=>r.str());}
    if(st==='DateTime'||st==='Timespan'){r.ensure(8);r.p+=8;return {native:st,bytes:8};}
    return properties(r,p,depth+1);
   }
   case 'MapProperty':{
    const removed=r.i32();if(removed!==0)throw Error('Nonempty removed-map keys unsupported');const n=r.i32();if(n<0||n>100000)throw Error('Bad map count');
    return Array.from({length:n},(_,i)=>({key:value(r,t.args[0],p+'{key}',-1,depth+1),value:value(r,t.args[1],p+'{value}',-1,depth+1)}));
   }
   case 'SetProperty':{
    const removed=r.i32();if(removed!==0)throw Error('Nonempty removed-set unsupported');const n=r.i32();if(n<0||n>100000)throw Error('Bad set count');return Array.from({length:n},()=>value(r,t.args[0],p+'{}',-1,depth+1));
   }
   case 'ArrayProperty':{
    const n=r.i32();if(n<0||n>100000)throw Error('Bad array count');return Array.from({length:n},()=>value(r,t.args[0],p+'[]',0,depth+1));
   }
   default:throw Error('Unsupported type '+typeText(t));
  }
 }
 function properties(r,prefix,depth=0){
  const result=[];
  while(r.p<r.end){
   const tagOffset=r.p,n=r.str();if(n==='None')return result;
   const t=r.type(),size=r.i32(),flags=r.u8();if(flags&~63)throw Error('Unknown tag flags');if(flags&1)r.i32();if(flags&2){r.ensure(16);r.p+=16;}
   if(flags&4){const ext=r.u8();if(ext&~3)throw Error('Unknown extensions');if(ext&2){r.u8();r.i32();}}
   r.ensure(size);const payloadOffset=r.p,end=r.p+size,propertyPath=prefix?prefix+'.'+n:n;
   const prop={name:n,type:typeText(t),flags,size,tagOffset,payloadOffset};
   const entry={save:name,path:propertyPath,type:prop.type,flags,size,tagOffset,payloadOffset};
   const sub=new Reader(r.p,end);
   try{prop.value=value(sub,t,propertyPath,flags,depth+1);if(sub.p!==end)throw Error(`Payload consumption ${sub.p-payloadOffset}/${size}`);prop.status='decoded';}
   catch(e){delete prop.value;prop.status='opaque';prop.reason=e.message;}
   entry.status=prop.status;entry.reason=prop.reason;schema.push(entry);result.push(prop);r.p=end;
  }
  throw Error('Missing None property terminator');
 }
 const r=new Reader(h.propertyDataOffset);
 // Archive adds a zero byte before the reflected tagged-property stream.
 const preamble=r.u8();if(preamble!==0)throw Error('Unsupported archive preamble');
 const props=properties(r,'');
 if(b.length-r.p!==4||b.readUInt32LE(r.p)!==0)throw Error('Unexpected save trailer');
 if(schema.some(p=>p.status!=='decoded'))throw Error('Opaque properties; refuse evidence');
 return {header:h,properties:props,schema,position:r.p,length:b.length};
}
