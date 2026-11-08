export const DIMENSIONS=['研究问题','文献与理论','研究方法','分析与论证','结论与价值','学术写作','格式规范'];
export const DEFAULT_WEIGHTS=[15,15,20,20,10,10,10];
export type PaperStatus='done'|'review'|'processing'|'queued'|'failed';
export type Page='cover'|'workspace'|'review';
export type SettingsSection='model'|'criteria'|'data';
export interface DimensionResult {dimension_id:string;name:string;score:number|null;max_score:number;reason:string;needs_teacher_review:boolean;evidence:{page:number;quote:string;verified:boolean;chunk_id:string}[];suggestions:string[];check_scores?:{index:number;text:string;score:number|null;max_score:number;reason:string}[]}
export interface Report {evaluation_id:string;is_mock:boolean;summary:string;notice:string;dimensions:DimensionResult[];diagnostics:string[];teacher_review:{total_score:number|null;confirmed:boolean}}
export interface LiveAnalysis {stage:string;phase:'connecting'|'analyzing'|'generating'|'validating'|'complete'|'failed';startedAt:number;updatedAt:number;reasoningCharacters:number;outputCharacters:number;draft:string;streaming:boolean|null;events:{text:string;at:number}[]}
export interface Paper {id:string;name:string;title:string;student:string;studentId:string;status:PaperStatus;scores:(number|null)[];totalScore:number|null;reviewed?:boolean;teacherNote?:string;error?:string;isUserFile?:boolean;bytes?:number;report:Report|null;live?:LiveAnalysis|null;pages:{number:number;text:string;status:string}[];parsing:{status:string;warnings:string[]}|null}
export interface ModelSettings {provider:string;url:string;model:string;key:string;configured:boolean;keySaved?:boolean}
export interface ModelTestResult {message:string;reply:string;model:string;elapsedMs:number}
export interface Rubric {id:string;name:string;version:string;dimensions:{id:string;name:string;max_score:number;description:string;checklist:string[];checklist_scores?:number[]}[]}
export interface Provider {name:string;url:string;documentation?:string;note?:string}
export interface AppState {mode:'real'|'mock';papers:Paper[];model:ModelSettings;rubric:Rubric;rubrics:Rubric[];rubricPresets:Rubric[];providers:Provider[];running:boolean;pauseRequested:boolean;progress:string;bytes:number}
export const STATUS_TEXT:Record<PaperStatus,string>={done:'已完成',review:'建议复核',processing:'评阅中',queued:'等待评阅',failed:'处理失败'};
export const STATUS_CLASS:Record<PaperStatus,string>={done:'status-done',review:'status-review',processing:'status-processing',queued:'status-queued',failed:'status-failed'};
export const EMPTY_MODEL:ModelSettings={provider:'自定义',url:'',model:'',key:'',configured:false};
export const hasResult=(paper:Paper)=>!!paper.report;
export const hasScore=(paper:Paper)=>!!paper.report&&paper.totalScore!==null;
export function paperScore(paper:Paper,_weights:number[]){return paper.totalScore??0;}
export function batchSummary(papers:Paper[],weights:number[]){const scored=papers.filter(hasScore),scores=scored.map(p=>paperScore(p,weights));return {scored,count:scored.length,processed:papers.filter(hasResult).length,mean:scores.length?scores.reduce((a,b)=>a+b,0)/scores.length:null,pendingReview:papers.filter(p=>p.report&&!p.reviewed).length,means:weights.map((_,i)=>scored.length?scored.reduce((sum,p)=>sum+(p.scores[i]??0),0)/scored.length:0),bins:[0,0,0,0,0].map((_,i)=>scores.filter(s=>i===0?s<60:i===4?s>=90:s>=50+i*10&&s<60+i*10).length)};}
export function readPage():Page{const v=new URLSearchParams(location.search).get('view');return v==='workspace'||v==='review'?v:'cover';}
export function formatBytes(bytes:number){return bytes<1024?`${bytes} B`:bytes<1024*1024?`${(bytes/1024).toFixed(1)} KB`:`${(bytes/1024/1024).toFixed(1)} MB`;}
