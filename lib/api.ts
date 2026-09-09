export type Claim = {text: string; citations: {source_id:string; quote:string}[]};
export type Hypothesis = {text:string; validation_step:string};
export type Source = {id:string; title:string; url:string; snippet:string; retrieved_at:string; query:string};
export type Costs = {currency:string; sale_price:string; unit_cost:string; shipping:string; other_costs:string; fee_percent:string};
export type Report = {
 overview:Claim; observations:Claim[]; competitors:Claim[]; rationale:Claim;
 opportunities:Hypothesis[]; risks:Hypothesis[]; assessment:string; limitations:string[];
 sources:Source[]; price_mentions:{source_id:string; text:string}[];
 calculation:null|{error?:string; currency:string; inputs:Costs; fees:string; contribution_per_unit:string; contribution_margin_percent:string; basis:string};
};
export type Job = {id:string; idea:string; status:string; created_at:number; error:string|null};
export type Detail = Job & {report:Report|null; inputs:{idea:string; costs:Costs|null}; events:{id:number;tool:string;status:string;detail:string;created_at:number}[]};
export type Session = {configured:boolean;message:string;daily_limit:number;retention_days:number};

export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
 const response = await fetch('/api'+path, {...options, credentials:'same-origin',
  headers:{'Content-Type':'application/json',...options.headers}, signal:options.signal ?? AbortSignal.timeout(15000)});
 const data = await response.json().catch(()=>null);
 if(!response.ok) throw new Error(data && typeof data==='object' && 'detail' in data && typeof data.detail==='string' ? data.detail : `Request failed (${response.status}).`);
 if(data === null) throw new Error('The server returned an unreadable response.');
 return data as T;
}

export function exportReport(detail:Detail) {
 const url=URL.createObjectURL(new Blob([JSON.stringify(detail,null,2)],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download=`fieldwork-${detail.id}.json`;link.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);
}
