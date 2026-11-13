import{g as dh}from"./_commonjsHelpers-CqkleIqs.js";import{o as ph,d as ch,l as hh}from"./index-KGLhDBEF.js";function fh(F,ge){for(var Oe=0;Oe<ge.length;Oe++){const ye=ge[Oe];if(typeof ye!="string"&&!Array.isArray(ye)){for(const ve in ye)if(ve!=="default"&&!(ve in F)){const me=Object.getOwnPropertyDescriptor(ye,ve);me&&Object.defineProperty(F,ve,me.get?me:{enumerable:!0,get:()=>ye[ve]})}}}return Object.freeze(Object.defineProperty(F,Symbol.toStringTag,{value:"Module"}))}function xt(F){throw new Error('Could not dynamically require "'+F+'". Please configure the dynamicRequireTargets or/and ignoreDynamicRequires option of @rollup/plugin-commonjs appropriately for this require call to work.')}var is={exports:{}};var Wp;function uc(){return Wp||(Wp=1,(function(F,ge){var Oe=(()=>{var ye=Object.defineProperty,ve=Object.getOwnPropertyDescriptor,me=Object.getOwnPropertyNames,J=Object.prototype.hasOwnProperty,G=(c=>typeof xt<"u"?xt:typeof Proxy<"u"?new Proxy(c,{get:(g,b)=>(typeof xt<"u"?xt:g)[b]}):c)(function(c){if(typeof xt<"u")return xt.apply(this,arguments);throw Error('Dynamic require of "'+c+'" is not supported')}),I=(c,g)=>()=>(c&&(g=c(c=0)),g),H=(c,g)=>{for(var b in g)ye(c,b,{get:g[b],enumerable:!0})},le=(c,g,b,T)=>{if(g&&typeof g=="object"||typeof g=="function")for(let x of me(g))!J.call(c,x)&&x!==b&&ye(c,x,{get:()=>g[x],enumerable:!(T=ve(g,x))||T.enumerable});return c},we=c=>le(ye({},"__esModule",{value:!0}),c),he,ne,Q,Y,Ce,Ne=I(()=>{he=new Map,ne=[],Q=(c,g,b)=>{if(g&&typeof g.init=="function"&&typeof g.createInferenceSessionHandler=="function"){let T=he.get(c);if(T===void 0)he.set(c,{backend:g,priority:b});else{if(T.priority>b)return;if(T.priority===b&&T.backend!==g)throw new Error(`cannot register backend "${c}" using priority ${b}`)}if(b>=0){let x=ne.indexOf(c);x!==-1&&ne.splice(x,1);for(let O=0;O<ne.length;O++)if(he.get(ne[O]).priority<=b){ne.splice(O,0,c);return}ne.push(c)}return}throw new TypeError("not a valid backend")},Y=async c=>{let g=he.get(c);if(!g)return"backend not found.";if(g.initialized)return g.backend;if(g.aborted)return g.error;{let b=!!g.initPromise;try{return b||(g.initPromise=g.backend.init(c)),await g.initPromise,g.initialized=!0,g.backend}catch(T){return b||(g.error=`${T}`,g.aborted=!0),g.error}finally{delete g.initPromise}}},Ce=async c=>{let g=c.executionProviders||[],b=g.map(A=>typeof A=="string"?A:A.name),T=b.length===0?ne:b,x,O=[],C=new Set;for(let A of T){let N=await Y(A);typeof N=="string"?O.push({name:A,err:N}):(x||(x=N),x===N&&C.add(A))}if(!x)throw new Error(`no available backend found. ERR: ${O.map(A=>`[${A.name}] ${A.err}`).join(", ")}`);for(let{name:A,err:N}of O)b.includes(A)&&console.warn(`removing requested execution provider "${A}" from session options because it is not available: ${N}`);let k=g.filter(A=>C.has(typeof A=="string"?A:A.name));return[x,new Proxy(c,{get:(A,N)=>N==="executionProviders"?k:Reflect.get(A,N)})]}}),ze=I(()=>{Ne()}),Te,_e=I(()=>{Te="1.24.3"}),Re,pe,Fe=I(()=>{_e(),Re="warning",pe={wasm:{},webgl:{},webgpu:{},versions:{common:Te},set logLevel(c){if(c!==void 0){if(typeof c!="string"||["verbose","info","warning","error","fatal"].indexOf(c)===-1)throw new Error(`Unsupported logging level: ${c}`);Re=c}},get logLevel(){return Re}},Object.defineProperty(pe,"logLevel",{enumerable:!0})}),ie,et=I(()=>{Fe(),ie=pe}),lt,St,_t=I(()=>{lt=(c,g)=>{let b=typeof document<"u"?document.createElement("canvas"):new OffscreenCanvas(1,1);b.width=c.dims[3],b.height=c.dims[2];let T=b.getContext("2d");if(T!=null){let x,O;g?.tensorLayout!==void 0&&g.tensorLayout==="NHWC"?(x=c.dims[2],O=c.dims[3]):(x=c.dims[3],O=c.dims[2]);let C=g?.format!==void 0?g.format:"RGB",k=g?.norm,A,N;k===void 0||k.mean===void 0?A=[255,255,255,255]:typeof k.mean=="number"?A=[k.mean,k.mean,k.mean,k.mean]:(A=[k.mean[0],k.mean[1],k.mean[2],0],k.mean[3]!==void 0&&(A[3]=k.mean[3])),k===void 0||k.bias===void 0?N=[0,0,0,0]:typeof k.bias=="number"?N=[k.bias,k.bias,k.bias,k.bias]:(N=[k.bias[0],k.bias[1],k.bias[2],0],k.bias[3]!==void 0&&(N[3]=k.bias[3]));let V=O*x,P=0,D=V,ee=V*2,z=-1;C==="RGBA"?(P=0,D=V,ee=V*2,z=V*3):C==="RGB"?(P=0,D=V,ee=V*2):C==="RBG"&&(P=0,ee=V,D=V*2);for(let q=0;q<O;q++)for(let qe=0;qe<x;qe++){let xe=(c.data[P++]-N[0])*A[0],te=(c.data[D++]-N[1])*A[1],Se=(c.data[ee++]-N[2])*A[2],Z=z===-1?255:(c.data[z++]-N[3])*A[3];T.fillStyle="rgba("+xe+","+te+","+Se+","+Z+")",T.fillRect(qe,q,1,1)}if("toDataURL"in b)return b.toDataURL();throw new Error("toDataURL is not supported")}else throw new Error("Can not access image data")},St=(c,g)=>{let b=typeof document<"u"?document.createElement("canvas").getContext("2d"):new OffscreenCanvas(1,1).getContext("2d"),T;if(b!=null){let x,O,C;g?.tensorLayout!==void 0&&g.tensorLayout==="NHWC"?(x=c.dims[2],O=c.dims[1],C=c.dims[3]):(x=c.dims[3],O=c.dims[2],C=c.dims[1]);let k=g!==void 0&&g.format!==void 0?g.format:"RGB",A=g?.norm,N,V;A===void 0||A.mean===void 0?N=[255,255,255,255]:typeof A.mean=="number"?N=[A.mean,A.mean,A.mean,A.mean]:(N=[A.mean[0],A.mean[1],A.mean[2],255],A.mean[3]!==void 0&&(N[3]=A.mean[3])),A===void 0||A.bias===void 0?V=[0,0,0,0]:typeof A.bias=="number"?V=[A.bias,A.bias,A.bias,A.bias]:(V=[A.bias[0],A.bias[1],A.bias[2],0],A.bias[3]!==void 0&&(V[3]=A.bias[3]));let P=O*x;if(g!==void 0&&(g.format!==void 0&&C===4&&g.format!=="RGBA"||C===3&&g.format!=="RGB"&&g.format!=="BGR"))throw new Error("Tensor format doesn't match input tensor dims");let D=4,ee=0,z=1,q=2,qe=3,xe=0,te=P,Se=P*2,Z=-1;k==="RGBA"?(xe=0,te=P,Se=P*2,Z=P*3):k==="RGB"?(xe=0,te=P,Se=P*2):k==="RBG"&&(xe=0,Se=P,te=P*2),T=b.createImageData(x,O);for(let rt=0;rt<O*x;ee+=D,z+=D,q+=D,qe+=D,rt++)T.data[ee]=(c.data[xe++]-V[0])*N[0],T.data[z]=(c.data[te++]-V[1])*N[1],T.data[q]=(c.data[Se++]-V[2])*N[2],T.data[qe]=Z===-1?255:(c.data[Z++]-V[3])*N[3]}else throw new Error("Can not access image data");return T}}),gt,pr,cr,Ue,jt,hr,Zr=I(()=>{mr(),gt=(c,g)=>{if(c===void 0)throw new Error("Image buffer must be defined");if(g.height===void 0||g.width===void 0)throw new Error("Image height and width must be defined");if(g.tensorLayout==="NHWC")throw new Error("NHWC Tensor layout is not supported yet");let{height:b,width:T}=g,x=g.norm??{mean:255,bias:0},O,C;typeof x.mean=="number"?O=[x.mean,x.mean,x.mean,x.mean]:O=[x.mean[0],x.mean[1],x.mean[2],x.mean[3]??255],typeof x.bias=="number"?C=[x.bias,x.bias,x.bias,x.bias]:C=[x.bias[0],x.bias[1],x.bias[2],x.bias[3]??0];let k=g.format!==void 0?g.format:"RGBA",A=g.tensorFormat!==void 0&&g.tensorFormat!==void 0?g.tensorFormat:"RGB",N=b*T,V=A==="RGBA"?new Float32Array(N*4):new Float32Array(N*3),P=4,D=0,ee=1,z=2,q=3,qe=0,xe=N,te=N*2,Se=-1;k==="RGB"&&(P=3,D=0,ee=1,z=2,q=-1),A==="RGBA"?Se=N*3:A==="RBG"?(qe=0,te=N,xe=N*2):A==="BGR"&&(te=0,xe=N,qe=N*2);for(let Z=0;Z<N;Z++,D+=P,z+=P,ee+=P,q+=P)V[qe++]=(c[D]+C[0])/O[0],V[xe++]=(c[ee]+C[1])/O[1],V[te++]=(c[z]+C[2])/O[2],Se!==-1&&q!==-1&&(V[Se++]=(c[q]+C[3])/O[3]);return A==="RGBA"?new Le("float32",V,[1,4,b,T]):new Le("float32",V,[1,3,b,T])},pr=async(c,g)=>{let b=typeof HTMLImageElement<"u"&&c instanceof HTMLImageElement,T=typeof ImageData<"u"&&c instanceof ImageData,x=typeof ImageBitmap<"u"&&c instanceof ImageBitmap,O=typeof c=="string",C,k=g??{},A=()=>{if(typeof document<"u")return document.createElement("canvas");if(typeof OffscreenCanvas<"u")return new OffscreenCanvas(1,1);throw new Error("Canvas is not supported")},N=V=>typeof HTMLCanvasElement<"u"&&V instanceof HTMLCanvasElement||V instanceof OffscreenCanvas?V.getContext("2d"):null;if(b){let V=A();V.width=c.width,V.height=c.height;let P=N(V);if(P!=null){let D=c.height,ee=c.width;if(g!==void 0&&g.resizedHeight!==void 0&&g.resizedWidth!==void 0&&(D=g.resizedHeight,ee=g.resizedWidth),g!==void 0){if(k=g,g.tensorFormat!==void 0)throw new Error("Image input config format must be RGBA for HTMLImageElement");k.tensorFormat="RGBA",k.height=D,k.width=ee}else k.tensorFormat="RGBA",k.height=D,k.width=ee;P.drawImage(c,0,0),C=P.getImageData(0,0,ee,D).data}else throw new Error("Can not access image data")}else if(T){let V,P;if(g!==void 0&&g.resizedWidth!==void 0&&g.resizedHeight!==void 0?(V=g.resizedHeight,P=g.resizedWidth):(V=c.height,P=c.width),g!==void 0&&(k=g),k.format="RGBA",k.height=V,k.width=P,g!==void 0){let D=A();D.width=P,D.height=V;let ee=N(D);if(ee!=null)ee.putImageData(c,0,0),C=ee.getImageData(0,0,P,V).data;else throw new Error("Can not access image data")}else C=c.data}else if(x){if(g===void 0)throw new Error("Please provide image config with format for Imagebitmap");let V=A();V.width=c.width,V.height=c.height;let P=N(V);if(P!=null){let D=c.height,ee=c.width;return P.drawImage(c,0,0,ee,D),C=P.getImageData(0,0,ee,D).data,k.height=D,k.width=ee,gt(C,k)}else throw new Error("Can not access image data")}else{if(O)return new Promise((V,P)=>{let D=A(),ee=N(D);if(!c||!ee)return P();let z=new Image;z.crossOrigin="Anonymous",z.src=c,z.onload=()=>{D.width=z.width,D.height=z.height,ee.drawImage(z,0,0,D.width,D.height);let q=ee.getImageData(0,0,D.width,D.height);k.height=D.height,k.width=D.width,V(gt(q.data,k))}});throw new Error("Input data provided is not supported - aborted tensor creation")}if(C!==void 0)return gt(C,k);throw new Error("Input data provided is not supported - aborted tensor creation")},cr=(c,g)=>{let{width:b,height:T,download:x,dispose:O}=g,C=[1,T,b,4];return new Le({location:"texture",type:"float32",texture:c,dims:C,download:x,dispose:O})},Ue=(c,g)=>{let{dataType:b,dims:T,download:x,dispose:O}=g;return new Le({location:"gpu-buffer",type:b??"float32",gpuBuffer:c,dims:T,download:x,dispose:O})},jt=(c,g)=>{let{dataType:b,dims:T,download:x,dispose:O}=g;return new Le({location:"ml-tensor",type:b??"float32",mlTensor:c,dims:T,download:x,dispose:O})},hr=(c,g,b)=>new Le({location:"cpu-pinned",type:c,data:g,dims:b??[g.length]})}),dt,Tt,fr,mi,qa=I(()=>{dt=new Map([["float32",Float32Array],["uint8",Uint8Array],["int8",Int8Array],["uint16",Uint16Array],["int16",Int16Array],["int32",Int32Array],["bool",Uint8Array],["float64",Float64Array],["uint32",Uint32Array],["int4",Uint8Array],["uint4",Uint8Array]]),Tt=new Map([[Float32Array,"float32"],[Uint8Array,"uint8"],[Int8Array,"int8"],[Uint16Array,"uint16"],[Int16Array,"int16"],[Int32Array,"int32"],[Float64Array,"float64"],[Uint32Array,"uint32"]]),fr=!1,mi=()=>{if(!fr){fr=!0;let c=typeof BigInt64Array<"u"&&BigInt64Array.from,g=typeof BigUint64Array<"u"&&BigUint64Array.from,b=globalThis.Float16Array,T=typeof b<"u"&&b.from;c&&(dt.set("int64",BigInt64Array),Tt.set(BigInt64Array,"int64")),g&&(dt.set("uint64",BigUint64Array),Tt.set(BigUint64Array,"uint64")),T?(dt.set("float16",b),Tt.set(b,"float16")):dt.set("float16",Uint16Array)}}}),gi,yi,Fa=I(()=>{mr(),gi=c=>{let g=1;for(let b=0;b<c.length;b++){let T=c[b];if(typeof T!="number"||!Number.isSafeInteger(T))throw new TypeError(`dims[${b}] must be an integer, got: ${T}`);if(T<0)throw new RangeError(`dims[${b}] must be a non-negative integer, got: ${T}`);g*=T}return g},yi=(c,g)=>{switch(c.location){case"cpu":return new Le(c.type,c.data,g);case"cpu-pinned":return new Le({location:"cpu-pinned",data:c.data,type:c.type,dims:g});case"texture":return new Le({location:"texture",texture:c.texture,type:c.type,dims:g});case"gpu-buffer":return new Le({location:"gpu-buffer",gpuBuffer:c.gpuBuffer,type:c.type,dims:g});case"ml-tensor":return new Le({location:"ml-tensor",mlTensor:c.mlTensor,type:c.type,dims:g});default:throw new Error(`tensorReshape: tensor location ${c.location} is not supported`)}}}),Le,mr=I(()=>{_t(),Zr(),qa(),Fa(),Le=class{constructor(c,g,b){mi();let T,x;if(typeof c=="object"&&"location"in c)switch(this.dataLocation=c.location,T=c.type,x=c.dims,c.location){case"cpu-pinned":{let C=dt.get(T);if(!C)throw new TypeError(`unsupported type "${T}" to create tensor from pinned buffer`);if(!(c.data instanceof C))throw new TypeError(`buffer should be of type ${C.name}`);this.cpuData=c.data;break}case"texture":{if(T!=="float32")throw new TypeError(`unsupported type "${T}" to create tensor from texture`);this.gpuTextureData=c.texture,this.downloader=c.download,this.disposer=c.dispose;break}case"gpu-buffer":{if(T!=="float32"&&T!=="float16"&&T!=="int32"&&T!=="int64"&&T!=="uint32"&&T!=="uint8"&&T!=="bool"&&T!=="uint4"&&T!=="int4")throw new TypeError(`unsupported type "${T}" to create tensor from gpu buffer`);this.gpuBufferData=c.gpuBuffer,this.downloader=c.download,this.disposer=c.dispose;break}case"ml-tensor":{if(T!=="float32"&&T!=="float16"&&T!=="int32"&&T!=="int64"&&T!=="uint32"&&T!=="uint64"&&T!=="int8"&&T!=="uint8"&&T!=="bool"&&T!=="uint4"&&T!=="int4")throw new TypeError(`unsupported type "${T}" to create tensor from MLTensor`);this.mlTensorData=c.mlTensor,this.downloader=c.download,this.disposer=c.dispose;break}default:throw new Error(`Tensor constructor: unsupported location '${this.dataLocation}'`)}else{let C,k;if(typeof c=="string")if(T=c,k=b,c==="string"){if(!Array.isArray(g))throw new TypeError("A string tensor's data must be a string array.");C=g}else{let A=dt.get(c);if(A===void 0)throw new TypeError(`Unsupported tensor type: ${c}.`);if(Array.isArray(g)){if(c==="float16"&&A===Uint16Array||c==="uint4"||c==="int4")throw new TypeError(`Creating a ${c} tensor from number array is not supported. Please use ${A.name} as data.`);c==="uint64"||c==="int64"?C=A.from(g,BigInt):C=A.from(g)}else if(g instanceof A)C=g;else if(g instanceof Uint8ClampedArray)if(c==="uint8")C=Uint8Array.from(g);else throw new TypeError("A Uint8ClampedArray tensor's data must be type of uint8");else if(c==="float16"&&g instanceof Uint16Array&&A!==Uint16Array)C=new globalThis.Float16Array(g.buffer,g.byteOffset,g.length);else throw new TypeError(`A ${T} tensor's data must be type of ${A}`)}else if(k=g,Array.isArray(c)){if(c.length===0)throw new TypeError("Tensor type cannot be inferred from an empty array.");let A=typeof c[0];if(A==="string")T="string",C=c;else if(A==="boolean")T="bool",C=Uint8Array.from(c);else throw new TypeError(`Invalid element type of data array: ${A}.`)}else if(c instanceof Uint8ClampedArray)T="uint8",C=Uint8Array.from(c);else{let A=Tt.get(c.constructor);if(A===void 0)throw new TypeError(`Unsupported type for tensor data: ${c.constructor}.`);T=A,C=c}if(k===void 0)k=[C.length];else if(!Array.isArray(k))throw new TypeError("A tensor's dims must be a number array");x=k,this.cpuData=C,this.dataLocation="cpu"}let O=gi(x);if(this.cpuData&&O!==this.cpuData.length&&!((T==="uint4"||T==="int4")&&Math.ceil(O/2)===this.cpuData.length))throw new Error(`Tensor's size(${O}) does not match data length(${this.cpuData.length}).`);this.type=T,this.dims=x,this.size=O}static async fromImage(c,g){return pr(c,g)}static fromTexture(c,g){return cr(c,g)}static fromGpuBuffer(c,g){return Ue(c,g)}static fromMLTensor(c,g){return jt(c,g)}static fromPinnedBuffer(c,g,b){return hr(c,g,b)}toDataURL(c){return lt(this,c)}toImageData(c){return St(this,c)}get data(){if(this.ensureValid(),!this.cpuData)throw new Error("The data is not on CPU. Use `getData()` to download GPU data to CPU, or use `texture` or `gpuBuffer` property to access the GPU data directly.");return this.cpuData}get location(){return this.dataLocation}get texture(){if(this.ensureValid(),!this.gpuTextureData)throw new Error("The data is not stored as a WebGL texture.");return this.gpuTextureData}get gpuBuffer(){if(this.ensureValid(),!this.gpuBufferData)throw new Error("The data is not stored as a WebGPU buffer.");return this.gpuBufferData}get mlTensor(){if(this.ensureValid(),!this.mlTensorData)throw new Error("The data is not stored as a WebNN MLTensor.");return this.mlTensorData}async getData(c){switch(this.ensureValid(),this.dataLocation){case"cpu":case"cpu-pinned":return this.data;case"texture":case"gpu-buffer":case"ml-tensor":{if(!this.downloader)throw new Error("The current tensor is not created with a specified data downloader.");if(this.isDownloading)throw new Error("The current tensor is being downloaded.");try{this.isDownloading=!0;let g=await this.downloader();return this.downloader=void 0,this.dataLocation="cpu",this.cpuData=g,c&&this.disposer&&(this.disposer(),this.disposer=void 0),g}finally{this.isDownloading=!1}}default:throw new Error(`cannot get data from location: ${this.dataLocation}`)}}dispose(){if(this.isDownloading)throw new Error("The current tensor is being downloaded.");this.disposer&&(this.disposer(),this.disposer=void 0),this.cpuData=void 0,this.gpuTextureData=void 0,this.gpuBufferData=void 0,this.mlTensorData=void 0,this.downloader=void 0,this.isDownloading=void 0,this.dataLocation="none"}ensureValid(){if(this.dataLocation==="none")throw new Error("The tensor is disposed.")}reshape(c){if(this.ensureValid(),this.downloader||this.disposer)throw new Error("Cannot reshape a tensor that owns GPU resource.");return yi(this,c)}}}),je,wi=I(()=>{mr(),je=Le}),Ut,gr,tt,Xe,st,ot,_i=I(()=>{Fe(),Ut=(c,g)=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||console.timeStamp(`${c}::ORT::${g}`)},gr=(c,g)=>{let b=new Error().stack?.split(/\r\n|\r|\n/g)||[],T=!1;for(let x=0;x<b.length;x++){if(T&&!b[x].includes("TRACE_FUNC")){let O=`FUNC_${c}::${b[x].trim().split(" ")[1]}`;g&&(O+=`::${g}`),Ut("CPU",O);return}b[x].includes("TRACE_FUNC")&&(T=!0)}},tt=c=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||gr("BEGIN",c)},Xe=c=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||gr("END",c)},st=c=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||console.time(`ORT::${c}`)},ot=c=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||console.timeEnd(`ORT::${c}`)}}),bi,Wa=I(()=>{Ne(),wi(),_i(),bi=class oc{constructor(g){this.handler=g}async run(g,b,T){tt(),st("InferenceSession.run");let x={},O={};if(typeof g!="object"||g===null||g instanceof je||Array.isArray(g))throw new TypeError("'feeds' must be an object that use input names as keys and OnnxValue as corresponding values.");let C=!0;if(typeof b=="object"){if(b===null)throw new TypeError("Unexpected argument[1]: cannot be null.");if(b instanceof je)throw new TypeError("'fetches' cannot be a Tensor");if(Array.isArray(b)){if(b.length===0)throw new TypeError("'fetches' cannot be an empty array.");C=!1;for(let N of b){if(typeof N!="string")throw new TypeError("'fetches' must be a string array or an object.");if(this.outputNames.indexOf(N)===-1)throw new RangeError(`'fetches' contains invalid output name: ${N}.`);x[N]=null}if(typeof T=="object"&&T!==null)O=T;else if(typeof T<"u")throw new TypeError("'options' must be an object.")}else{let N=!1,V=Object.getOwnPropertyNames(b);for(let P of this.outputNames)if(V.indexOf(P)!==-1){let D=b[P];(D===null||D instanceof je)&&(N=!0,C=!1,x[P]=D)}if(N){if(typeof T=="object"&&T!==null)O=T;else if(typeof T<"u")throw new TypeError("'options' must be an object.")}else O=b}}else if(typeof b<"u")throw new TypeError("Unexpected argument[1]: must be 'fetches' or 'options'.");for(let N of this.inputNames)if(typeof g[N]>"u")throw new Error(`input '${N}' is missing in 'feeds'.`);if(C)for(let N of this.outputNames)x[N]=null;let k=await this.handler.run(g,x,O),A={};for(let N in k)if(Object.hasOwnProperty.call(k,N)){let V=k[N];V instanceof je?A[N]=V:A[N]=new je(V.type,V.data,V.dims)}return ot("InferenceSession.run"),Xe(),A}async release(){return this.handler.dispose()}static async create(g,b,T,x){tt(),st("InferenceSession.create");let O,C={};if(typeof g=="string"){if(O=g,typeof b=="object"&&b!==null)C=b;else if(typeof b<"u")throw new TypeError("'options' must be an object.")}else if(g instanceof Uint8Array){if(O=g,typeof b=="object"&&b!==null)C=b;else if(typeof b<"u")throw new TypeError("'options' must be an object.")}else if(g instanceof ArrayBuffer||typeof SharedArrayBuffer<"u"&&g instanceof SharedArrayBuffer){let V=g,P=0,D=g.byteLength;if(typeof b=="object"&&b!==null)C=b;else if(typeof b=="number"){if(P=b,!Number.isSafeInteger(P))throw new RangeError("'byteOffset' must be an integer.");if(P<0||P>=V.byteLength)throw new RangeError(`'byteOffset' is out of range [0, ${V.byteLength}).`);if(D=g.byteLength-P,typeof T=="number"){if(D=T,!Number.isSafeInteger(D))throw new RangeError("'byteLength' must be an integer.");if(D<=0||P+D>V.byteLength)throw new RangeError(`'byteLength' is out of range (0, ${V.byteLength-P}].`);if(typeof x=="object"&&x!==null)C=x;else if(typeof x<"u")throw new TypeError("'options' must be an object.")}else if(typeof T<"u")throw new TypeError("'byteLength' must be a number.")}else if(typeof b<"u")throw new TypeError("'options' must be an object.");O=new Uint8Array(V,P,D)}else throw new TypeError("Unexpected argument[0]: must be 'path' or 'buffer'.");let[k,A]=await Ce(C),N=await k.createInferenceSessionHandler(O,A);return ot("InferenceSession.create"),Xe(),new oc(N)}startProfiling(){this.handler.startProfiling()}endProfiling(){this.handler.endProfiling()}get inputNames(){return this.handler.inputNames}get outputNames(){return this.handler.outputNames}get inputMetadata(){return this.handler.inputMetadata}get outputMetadata(){return this.handler.outputMetadata}}}),yr,Ga=I(()=>{Wa(),yr=bi}),ja=I(()=>{}),Ha=I(()=>{}),Ka=I(()=>{}),Za=I(()=>{}),$i={};H($i,{InferenceSession:()=>yr,TRACE:()=>Ut,TRACE_EVENT_BEGIN:()=>st,TRACE_EVENT_END:()=>ot,TRACE_FUNC_BEGIN:()=>tt,TRACE_FUNC_END:()=>Xe,Tensor:()=>je,env:()=>ie,registerBackend:()=>Q});var Ye=I(()=>{ze(),et(),Ga(),wi(),ja(),Ha(),_i(),Ka(),Za()}),wr=I(()=>{}),vi={};H(vi,{default:()=>xi});var _r,br,xi,Qa=I(()=>{qi(),ct(),Tr(),_r="ort-wasm-proxy-worker",br=globalThis.self?.name===_r,br&&(self.onmessage=c=>{let{type:g,in:b}=c.data;try{switch(g){case"init-wasm":Ir(b.wasm).then(()=>{Xr(b).then(()=>{postMessage({type:g})},T=>{postMessage({type:g,err:T})})},T=>{postMessage({type:g,err:T})});break;case"init-ep":{let{epName:T,env:x}=b;Yr(x,T).then(()=>{postMessage({type:g})},O=>{postMessage({type:g,err:O})});break}case"copy-from":{let{buffer:T}=b,x=Ae(T);postMessage({type:g,out:x});break}case"create":{let{model:T,options:x}=b;yt(T,x).then(O=>{postMessage({type:g,out:O})},O=>{postMessage({type:g,err:O})});break}case"release":ti(b),postMessage({type:g});break;case"run":{let{sessionId:T,inputIndices:x,inputs:O,outputIndices:C,options:k}=b;M(T,x,O,C,new Array(C.length).fill(null),k).then(A=>{A.some(N=>N[3]!=="cpu")?postMessage({type:g,err:"Proxy does not support non-cpu tensor location."}):postMessage({type:g,out:A},ri([...O,...A]))},A=>{postMessage({type:g,err:A})});break}case"end-profiling":rr(b),postMessage({type:g});break;default:}}catch(T){postMessage({type:g,err:T})}}),xi=br?null:c=>new Worker(c??Ve,{type:"classic",name:_r})}),Si,Ti,Ve,$r,Ht,Ei,ki,vr,Ii,xr,Ci,Sr,zi,Tr=I(()=>{wr(),Si=typeof location>"u"?void 0:location.origin,Ti=()=>typeof document<"u"?document.currentScript?.src:typeof self<"u"?self.location?.href:void 0,Ve=Ti(),$r=()=>{if(Ve&&!Ve.startsWith("blob:"))return Ve.substring(0,Ve.lastIndexOf("/")+1)},Ht=(c,g)=>{try{let b=g??Ve;return(b?new URL(c,b):new URL(c)).origin===Si}catch{return!1}},Ei=(c,g)=>{let b=g??Ve;try{return(b?new URL(c,b):new URL(c)).href}catch{return}},ki=(c,g)=>`${g??"./"}${c}`,vr=async c=>{let g=await(await fetch(c,{credentials:"same-origin"})).blob();return URL.createObjectURL(g)},Ii=async c=>(await import(c)).default,xr=(Qa(),we(vi)).default,Ci=async()=>{if(!Ve)throw new Error("Failed to load proxy worker: cannot determine the script source URL.");if(Ht(Ve))return[void 0,xr()];let c=await vr(Ve);return[c,xr(c)]},Sr=void 0,zi=async(c,g,b,T)=>{let x=Sr&&!(c||g);if(x)if(Ve)x=Ht(Ve)||T&&!b;else if(T&&!b)x=!0;else throw new Error("cannot determine the script source URL.");if(x)return[void 0,Sr];{let O="ort-wasm-simd-threaded.mjs",C=c??Ei(O,g),k=b&&C&&!Ht(C,g),A=k?await vr(C):C??ki(O,g);return[k?A:void 0,await Ii(A)]}}}),Er,Kt,Et,kr,Ai,Oi,Ri,Ir,ce,ct=I(()=>{Tr(),Kt=!1,Et=!1,kr=!1,Ai=()=>{if(typeof SharedArrayBuffer>"u")return!1;try{return typeof MessageChannel<"u"&&new MessageChannel().port1.postMessage(new SharedArrayBuffer(1)),WebAssembly.validate(new Uint8Array([0,97,115,109,1,0,0,0,1,4,1,96,0,0,3,2,1,0,5,4,1,3,1,1,10,11,1,9,0,65,0,254,16,2,0,26,11]))}catch{return!1}},Oi=()=>{try{return WebAssembly.validate(new Uint8Array([0,97,115,109,1,0,0,0,1,4,1,96,0,0,3,2,1,0,10,30,1,28,0,65,0,253,15,253,12,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,253,186,1,26,11]))}catch{return!1}},Ri=()=>{try{return WebAssembly.validate(new Uint8Array([0,97,115,109,1,0,0,0,1,5,1,96,0,1,123,3,2,1,0,10,19,1,17,0,65,1,253,15,65,2,253,15,65,3,253,15,253,147,2,11]))}catch{return!1}},Ir=async c=>{if(Kt)return Promise.resolve();if(Et)throw new Error("multiple calls to 'initializeWebAssembly()' detected.");if(kr)throw new Error("previous call to 'initializeWebAssembly()' failed.");Et=!0;let g=c.initTimeout,b=c.numThreads;if(c.simd!==!1){if(c.simd==="relaxed"){if(!Ri())throw new Error("Relaxed WebAssembly SIMD is not supported in the current environment.")}else if(!Oi())throw new Error("WebAssembly SIMD is not supported in the current environment.")}let T=Ai();b>1&&!T&&(typeof self<"u"&&!self.crossOriginIsolated&&console.warn("env.wasm.numThreads is set to "+b+", but this will not work unless you enable crossOriginIsolated mode. See https://web.dev/cross-origin-isolation-guide/ for more info."),console.warn("WebAssembly multi-threading is not supported in the current environment. Falling back to single-threading."),c.numThreads=b=1);let x=c.wasmPaths,O=typeof x=="string"?x:void 0,C=x?.mjs,k=C?.href??C,A=x?.wasm,N=A?.href??A,V=c.wasmBinary,[P,D]=await zi(k,O,b>1,!!V||!!N),ee=!1,z=[];if(g>0&&z.push(new Promise(q=>{setTimeout(()=>{ee=!0,q()},g)})),z.push(new Promise((q,qe)=>{let xe={numThreads:b};if(V)xe.wasmBinary=V,xe.locateFile=te=>te;else if(N||O)xe.locateFile=te=>N??O+te;else if(k&&k.indexOf("blob:")!==0)xe.locateFile=te=>new URL(te,k).href;else if(P){let te=$r();te&&(xe.locateFile=Se=>te+Se)}D(xe).then(te=>{Et=!1,Kt=!0,Er=te,q(),P&&URL.revokeObjectURL(P)},te=>{Et=!1,kr=!0,qe(te)})})),await Promise.race(z),ee)throw new Error(`WebAssembly backend initializing failed due to timeout: ${g}ms`)},ce=()=>{if(Kt&&Er)return Er;throw new Error("WebAssembly is not initialized yet.")}}),He,Zt,se,Cr=I(()=>{ct(),He=(c,g)=>{let b=ce(),T=b.lengthBytesUTF8(c)+1,x=b._malloc(T);return b.stringToUTF8(c,x,T),g.push(x),x},Zt=(c,g,b,T)=>{if(typeof c=="object"&&c!==null){if(b.has(c))throw new Error("Circular reference in options");b.add(c)}Object.entries(c).forEach(([x,O])=>{let C=g?g+x:x;if(typeof O=="object")Zt(O,C+".",b,T);else if(typeof O=="string"||typeof O=="number")T(C,O.toString());else if(typeof O=="boolean")T(C,O?"1":"0");else throw new Error(`Can't handle extra config type: ${typeof O}`)})},se=c=>{let g=ce(),b=g.stackSave();try{let T=g.PTR_SIZE,x=g.stackAlloc(2*T);g._OrtGetLastError(x,x+T);let O=Number(g.getValue(x,T===4?"i32":"i64")),C=g.getValue(x+T,"*"),k=C?g.UTF8ToString(C):"";throw new Error(`${c} ERROR_CODE: ${O}, ERROR_MESSAGE: ${k}`)}finally{g.stackRestore(b)}}}),Bi,Xa=I(()=>{ct(),Cr(),Bi=c=>{let g=ce(),b=0,T=[],x=c||{};try{if(c?.logSeverityLevel===void 0)x.logSeverityLevel=2;else if(typeof c.logSeverityLevel!="number"||!Number.isInteger(c.logSeverityLevel)||c.logSeverityLevel<0||c.logSeverityLevel>4)throw new Error(`log severity level is not valid: ${c.logSeverityLevel}`);if(c?.logVerbosityLevel===void 0)x.logVerbosityLevel=0;else if(typeof c.logVerbosityLevel!="number"||!Number.isInteger(c.logVerbosityLevel))throw new Error(`log verbosity level is not valid: ${c.logVerbosityLevel}`);c?.terminate===void 0&&(x.terminate=!1);let O=0;return c?.tag!==void 0&&(O=He(c.tag,T)),b=g._OrtCreateRunOptions(x.logSeverityLevel,x.logVerbosityLevel,!!x.terminate,O),b===0&&se("Can't create run options."),c?.extra!==void 0&&Zt(c.extra,"",new WeakSet,(C,k)=>{let A=He(C,T),N=He(k,T);g._OrtAddRunConfigEntry(b,A,N)!==0&&se(`Can't set a run config entry: ${C} - ${k}.`)}),[b,T]}catch(O){throw b!==0&&g._OrtReleaseRunOptions(b),T.forEach(C=>g._free(C)),O}}}),Mi,Di,Pi,kt,Ui,Ni,Ya=I(()=>{ct(),Cr(),Mi=c=>{switch(c){case"disabled":return 0;case"basic":return 1;case"extended":return 2;case"layout":return 3;case"all":return 99;default:throw new Error(`unsupported graph optimization level: ${c}`)}},Di=c=>{switch(c){case"sequential":return 0;case"parallel":return 1;default:throw new Error(`unsupported execution mode: ${c}`)}},Pi=c=>{c.extra||(c.extra={}),c.extra.session||(c.extra.session={});let g=c.extra.session;g.use_ort_model_bytes_directly||(g.use_ort_model_bytes_directly="1"),c.executionProviders&&c.executionProviders.some(b=>(typeof b=="string"?b:b.name)==="webgpu")&&(c.enableMemPattern=!1)},kt=(c,g,b,T)=>{let x=He(g,T),O=He(b,T);ce()._OrtAddSessionConfigEntry(c,x,O)!==0&&se(`Can't set a session config entry: ${g} - ${b}.`)},Ui=async(c,g,b)=>{let T=g.executionProviders;for(let x of T){let O=typeof x=="string"?x:x.name,C=[];switch(O){case"webnn":if(O="WEBNN",typeof x!="string"){let P=x?.deviceType;P&&kt(c,"deviceType",P,b)}break;case"webgpu":if(O="JS",typeof x!="string"){let P=x;if(P?.preferredLayout){if(P.preferredLayout!=="NCHW"&&P.preferredLayout!=="NHWC")throw new Error(`preferredLayout must be either 'NCHW' or 'NHWC': ${P.preferredLayout}`);kt(c,"preferredLayout",P.preferredLayout,b)}}break;case"wasm":case"cpu":continue;default:throw new Error(`not supported execution provider: ${O}`)}let k=He(O,b),A=C.length,N=0,V=0;if(A>0){N=ce()._malloc(A*ce().PTR_SIZE),b.push(N),V=ce()._malloc(A*ce().PTR_SIZE),b.push(V);for(let P=0;P<A;P++)ce().setValue(N+P*ce().PTR_SIZE,C[P][0],"*"),ce().setValue(V+P*ce().PTR_SIZE,C[P][1],"*")}await ce()._OrtAppendExecutionProvider(c,k,N,V,A)!==0&&se(`Can't append execution provider: ${O}.`)}},Ni=async c=>{let g=ce(),b=0,T=[],x=c||{};Pi(x);try{let O=Mi(x.graphOptimizationLevel??"all"),C=Di(x.executionMode??"sequential"),k=typeof x.logId=="string"?He(x.logId,T):0,A=x.logSeverityLevel??2;if(!Number.isInteger(A)||A<0||A>4)throw new Error(`log severity level is not valid: ${A}`);let N=x.logVerbosityLevel??0;if(!Number.isInteger(N)||N<0||N>4)throw new Error(`log verbosity level is not valid: ${N}`);let V=typeof x.optimizedModelFilePath=="string"?He(x.optimizedModelFilePath,T):0;if(b=g._OrtCreateSessionOptions(O,!!x.enableCpuMemArena,!!x.enableMemPattern,C,!!x.enableProfiling,0,k,A,N,V),b===0&&se("Can't create session options."),x.executionProviders&&await Ui(b,x,T),x.enableGraphCapture!==void 0){if(typeof x.enableGraphCapture!="boolean")throw new Error(`enableGraphCapture must be a boolean value: ${x.enableGraphCapture}`);kt(b,"enableGraphCapture",x.enableGraphCapture.toString(),T)}if(x.freeDimensionOverrides)for(let[P,D]of Object.entries(x.freeDimensionOverrides)){if(typeof P!="string")throw new Error(`free dimension override name must be a string: ${P}`);if(typeof D!="number"||!Number.isInteger(D)||D<0)throw new Error(`free dimension override value must be a non-negative integer: ${D}`);let ee=He(P,T);g._OrtAddFreeDimensionOverride(b,ee,D)!==0&&se(`Can't set a free dimension override: ${P} - ${D}.`)}return x.extra!==void 0&&Zt(x.extra,"",new WeakSet,(P,D)=>{kt(b,P,D,T)}),[b,T]}catch(O){throw b!==0&&g._OrtReleaseSessionOptions(b)!==0&&se("Can't release session options."),T.forEach(C=>g._free(C)),O}}}),ht,ft,mt,zr,Ar,Or,Rr,Qr,ue=I(()=>{ht=c=>{switch(c){case"int8":return 3;case"uint8":return 2;case"bool":return 9;case"int16":return 5;case"uint16":return 4;case"int32":return 6;case"uint32":return 12;case"float16":return 10;case"float32":return 1;case"float64":return 11;case"string":return 8;case"int64":return 7;case"uint64":return 13;case"int4":return 22;case"uint4":return 21;default:throw new Error(`unsupported data type: ${c}`)}},ft=c=>{switch(c){case 3:return"int8";case 2:return"uint8";case 9:return"bool";case 5:return"int16";case 4:return"uint16";case 6:return"int32";case 12:return"uint32";case 10:return"float16";case 1:return"float32";case 11:return"float64";case 8:return"string";case 7:return"int64";case 13:return"uint64";case 22:return"int4";case 21:return"uint4";default:throw new Error(`unsupported data type: ${c}`)}},mt=(c,g)=>{let b=[-1,4,1,1,2,2,4,8,-1,1,2,8,4,8,-1,-1,-1,-1,-1,-1,-1,.5,.5][c],T=typeof g=="number"?g:g.reduce((x,O)=>x*O,1);return b>0?Math.ceil(T*b):void 0},zr=c=>{switch(c){case"float16":return typeof Float16Array<"u"&&Float16Array.from?Float16Array:Uint16Array;case"float32":return Float32Array;case"uint8":return Uint8Array;case"int8":return Int8Array;case"uint16":return Uint16Array;case"int16":return Int16Array;case"int32":return Int32Array;case"bool":return Uint8Array;case"float64":return Float64Array;case"uint32":return Uint32Array;case"int64":return BigInt64Array;case"uint64":return BigUint64Array;default:throw new Error(`unsupported type: ${c}`)}},Ar=c=>{switch(c){case"verbose":return 0;case"info":return 1;case"warning":return 2;case"error":return 3;case"fatal":return 4;default:throw new Error(`unsupported logging level: ${c}`)}},Or=c=>c==="float32"||c==="float16"||c==="int32"||c==="int64"||c==="uint32"||c==="uint8"||c==="bool"||c==="uint4"||c==="int4",Rr=c=>c==="float32"||c==="float16"||c==="int32"||c==="int64"||c==="uint32"||c==="uint64"||c==="int8"||c==="uint8"||c==="bool"||c==="uint4"||c==="int4",Qr=c=>{switch(c){case"none":return 0;case"cpu":return 1;case"cpu-pinned":return 2;case"texture":return 3;case"gpu-buffer":return 4;case"ml-tensor":return 5;default:throw new Error(`unsupported data location: ${c}`)}}}),Br,Li=I(()=>{wr(),Br=async c=>{if(typeof c=="string"){let g=await fetch(c);if(!g.ok)throw new Error(`failed to load external data file: ${c}`);let b=g.headers.get("Content-Length"),T=b?parseInt(b,10):0;if(T<1073741824)return new Uint8Array(await g.arrayBuffer());{if(!g.body)throw new Error(`failed to load external data file: ${c}, no response body.`);let x=g.body.getReader(),O;try{O=new ArrayBuffer(T)}catch(k){if(k instanceof RangeError){let A=Math.ceil(T/65536);O=new WebAssembly.Memory({initial:A,maximum:A}).buffer}else throw k}let C=0;for(;;){let{done:k,value:A}=await x.read();if(k)break;let N=A.byteLength;new Uint8Array(O,C,N).set(A),C+=N}return new Uint8Array(O,0,T)}}else return c instanceof Blob?new Uint8Array(await c.arrayBuffer()):c instanceof Uint8Array?c:new Uint8Array(c)}}),Vi,Xr,Yr,Nt,Jr,ei,Ae,yt,ti,Lt,M,rr,ri,qi=I(()=>{Ye(),Xa(),Ya(),ue(),ct(),Cr(),Li(),Vi=(c,g)=>{ce()._OrtInit(c,g)!==0&&se("Can't initialize onnxruntime.")},Xr=async c=>{Vi(c.wasm.numThreads,Ar(c.logLevel))},Yr=async(c,g)=>{ce().asyncInit?.();let b=c.webgpu.adapter;if(g==="webgpu"){if(typeof navigator>"u"||!navigator.gpu)throw new Error("WebGPU is not supported in current environment");if(b){if(typeof b.limits!="object"||typeof b.features!="object"||typeof b.requestDevice!="function")throw new Error("Invalid GPU adapter set in `env.webgpu.adapter`. It must be a GPUAdapter object.")}else{let T=c.webgpu.powerPreference;if(T!==void 0&&T!=="low-power"&&T!=="high-performance")throw new Error(`Invalid powerPreference setting: "${T}"`);let x=c.webgpu.forceFallbackAdapter;if(x!==void 0&&typeof x!="boolean")throw new Error(`Invalid forceFallbackAdapter setting: "${x}"`);if(b=await navigator.gpu.requestAdapter({powerPreference:T,forceFallbackAdapter:x}),!b)throw new Error('Failed to get GPU adapter. You may need to enable flag "--enable-unsafe-webgpu" if you are using Chrome.')}}if(g==="webnn"&&(typeof navigator>"u"||!navigator.ml))throw new Error("WebNN is not supported in current environment")},Nt=new Map,Jr=c=>{let g=ce(),b=g.stackSave();try{let T=g.PTR_SIZE,x=g.stackAlloc(2*T);g._OrtGetInputOutputCount(c,x,x+T)!==0&&se("Can't get session input/output count.");let O=T===4?"i32":"i64";return[Number(g.getValue(x,O)),Number(g.getValue(x+T,O))]}finally{g.stackRestore(b)}},ei=(c,g)=>{let b=ce(),T=b.stackSave(),x=0;try{let O=b.PTR_SIZE,C=b.stackAlloc(2*O);b._OrtGetInputOutputMetadata(c,g,C,C+O)!==0&&se("Can't get session input/output metadata.");let k=Number(b.getValue(C,"*"));x=Number(b.getValue(C+O,"*"));let A=b.HEAP32[x/4];if(A===0)return[k,0];let N=b.HEAPU32[x/4+1],V=[];for(let P=0;P<N;P++){let D=Number(b.getValue(x+8+P*O,"*"));V.push(D!==0?b.UTF8ToString(D):Number(b.getValue(x+8+(P+N)*O,"*")))}return[k,A,V]}finally{b.stackRestore(T),x!==0&&b._OrtFree(x)}},Ae=c=>{let g=ce(),b=g._malloc(c.byteLength);if(b===0)throw new Error(`Can't create a session. failed to allocate a buffer of size ${c.byteLength}.`);return g.HEAPU8.set(c,b),[b,c.byteLength]},yt=async(c,g)=>{let b,T,x=ce();Array.isArray(c)?[b,T]=c:c.buffer===x.HEAPU8.buffer?[b,T]=[c.byteOffset,c.byteLength]:[b,T]=Ae(c);let O=0,C=0,k=[],A=[],N=[];try{if([C,k]=await Ni(g),g?.externalData&&x.mountExternalData){let te=[];for(let Se of g.externalData){let Z=typeof Se=="string"?Se:Se.path;te.push(Br(typeof Se=="string"?Se:Se.data).then(rt=>{x.mountExternalData(Z,rt)}))}await Promise.all(te)}for(let te of g?.executionProviders??[])if((typeof te=="string"?te:te.name)==="webnn"){if(x.shouldTransferToMLTensor=!1,typeof te!="string"){let Se=te,Z=Se?.context,rt=Se?.gpuDevice,it=Se?.deviceType,Ft=Se?.powerPreference;Z?x.currentContext=Z:rt?x.currentContext=await x.webnnCreateMLContext(rt):x.currentContext=await x.webnnCreateMLContext({deviceType:it,powerPreference:Ft})}else x.currentContext=await x.webnnCreateMLContext();break}O=await x._OrtCreateSession(b,T,C),x.webgpuOnCreateSession?.(O),O===0&&se("Can't create a session."),x.jsepOnCreateSession?.(),x.currentContext&&(x.webnnRegisterMLContext(O,x.currentContext),x.currentContext=void 0,x.shouldTransferToMLTensor=!0);let[V,P]=Jr(O),D=!!g?.enableGraphCapture,ee=[],z=[],q=[],qe=[],xe=[];for(let te=0;te<V;te++){let[Se,Z,rt]=ei(O,te);Se===0&&se("Can't get an input name."),A.push(Se);let it=x.UTF8ToString(Se);ee.push(it),q.push(Z===0?{name:it,isTensor:!1}:{name:it,isTensor:!0,type:ft(Z),shape:rt})}for(let te=0;te<P;te++){let[Se,Z,rt]=ei(O,te+V);Se===0&&se("Can't get an output name."),N.push(Se);let it=x.UTF8ToString(Se);z.push(it),qe.push(Z===0?{name:it,isTensor:!1}:{name:it,isTensor:!0,type:ft(Z),shape:rt})}return Nt.set(O,[O,A,N,null,D,!1]),[O,ee,z,q,qe]}catch(V){throw A.forEach(P=>x._OrtFree(P)),N.forEach(P=>x._OrtFree(P)),O!==0&&x._OrtReleaseSession(O)!==0&&se("Can't release session."),V}finally{x._free(b),C!==0&&x._OrtReleaseSessionOptions(C)!==0&&se("Can't release session options."),k.forEach(V=>x._free(V)),x.unmountExternalData?.()}},ti=c=>{let g=ce(),b=Nt.get(c);if(!b)throw new Error(`cannot release session. invalid session id: ${c}`);let[T,x,O,C,k]=b;C&&(k&&g._OrtClearBoundOutputs(C.handle)!==0&&se("Can't clear bound outputs."),g._OrtReleaseBinding(C.handle)!==0&&se("Can't release IO binding.")),g.jsepOnReleaseSession?.(c),g.webnnOnReleaseSession?.(c),g.webgpuOnReleaseSession?.(c),x.forEach(A=>g._OrtFree(A)),O.forEach(A=>g._OrtFree(A)),g._OrtReleaseSession(T)!==0&&se("Can't release session."),Nt.delete(c)},Lt=async(c,g,b,T,x,O,C=!1)=>{if(!c){g.push(0);return}let k=ce(),A=k.PTR_SIZE,N=c[0],V=c[1],P=c[3],D=P,ee,z;if(N==="string"&&(P==="gpu-buffer"||P==="ml-tensor"))throw new Error("String tensor is not supported on GPU.");if(C&&P!=="gpu-buffer")throw new Error(`External buffer must be provided for input/output index ${O} when enableGraphCapture is true.`);if(P==="gpu-buffer"){let xe=c[2].gpuBuffer;z=mt(ht(N),V);{let te=k.jsepRegisterBuffer;if(!te)throw new Error('Tensor location "gpu-buffer" is not supported without using WebGPU.');ee=te(T,O,xe,z)}}else if(P==="ml-tensor"){let xe=c[2].mlTensor;z=mt(ht(N),V);let te=k.webnnRegisterMLTensor;if(!te)throw new Error('Tensor location "ml-tensor" is not supported without using WebNN.');ee=te(T,xe,ht(N),V)}else{let xe=c[2];if(Array.isArray(xe)){z=A*xe.length,ee=k._malloc(z),b.push(ee);for(let te=0;te<xe.length;te++){if(typeof xe[te]!="string")throw new TypeError(`tensor data at index ${te} is not a string`);k.setValue(ee+te*A,He(xe[te],b),"*")}}else{let te=k.webnnIsGraphInput,Se=k.webnnIsGraphOutput;if(N!=="string"&&te&&Se){let Z=k.UTF8ToString(x);if(te(T,Z)||Se(T,Z)){let rt=ht(N);z=mt(rt,V),D="ml-tensor";let it=k.webnnCreateTemporaryTensor,Ft=k.webnnUploadTensor;if(!it||!Ft)throw new Error('Tensor location "ml-tensor" is not supported without using WebNN.');let sr=await it(T,rt,V);Ft(sr,new Uint8Array(xe.buffer,xe.byteOffset,xe.byteLength)),ee=sr}else z=xe.byteLength,ee=k._malloc(z),b.push(ee),k.HEAPU8.set(new Uint8Array(xe.buffer,xe.byteOffset,z),ee)}else z=xe.byteLength,ee=k._malloc(z),b.push(ee),k.HEAPU8.set(new Uint8Array(xe.buffer,xe.byteOffset,z),ee)}}let q=k.stackSave(),qe=k.stackAlloc(4*V.length);try{V.forEach((te,Se)=>k.setValue(qe+Se*A,te,A===4?"i32":"i64"));let xe=k._OrtCreateTensor(ht(N),ee,z,qe,V.length,Qr(D));xe===0&&se(`Can't create tensor for input/output. session=${T}, index=${O}.`),g.push(xe)}finally{k.stackRestore(q)}},M=async(c,g,b,T,x,O)=>{let C=ce(),k=C.PTR_SIZE,A=Nt.get(c);if(!A)throw new Error(`cannot run inference. invalid session id: ${c}`);let N=A[0],V=A[1],P=A[2],D=A[3],ee=A[4];A[5];let z=g.length,q=T.length,qe=0,xe=[],te=[],Se=[],Z=[],rt=[],it=C.stackSave(),Ft=C.stackAlloc(z*k),sr=C.stackAlloc(z*k),ci=C.stackAlloc(q*k),Qi=C.stackAlloc(q*k);try{[qe,xe]=Bi(O),st("wasm prepareInputOutputTensor");for(let Ee=0;Ee<z;Ee++)await Lt(b[Ee],te,Z,c,V[g[Ee]],g[Ee],ee);for(let Ee=0;Ee<q;Ee++)await Lt(x[Ee],Se,Z,c,P[T[Ee]],z+T[Ee],ee);ot("wasm prepareInputOutputTensor");for(let Ee=0;Ee<z;Ee++)C.setValue(Ft+Ee*k,te[Ee],"*"),C.setValue(sr+Ee*k,V[g[Ee]],"*");for(let Ee=0;Ee<q;Ee++)C.setValue(ci+Ee*k,Se[Ee],"*"),C.setValue(Qi+Ee*k,P[T[Ee]],"*");C.jsepOnRunStart?.(N),C.webnnOnRunStart?.(N);let We;We=await C._OrtRun(N,sr,Ft,z,Qi,q,ci,qe),We!==0&&se("failed to call OrtRun().");let bt=[],Xi=[];st("wasm ProcessOutputTensor");for(let Ee=0;Ee<q;Ee++){let wt=Number(C.getValue(ci+Ee*k,"*"));if(wt===Se[Ee]||rt.includes(Se[Ee])){bt.push(x[Ee]),wt!==Se[Ee]&&C._OrtReleaseTensor(wt)!==0&&se("Can't release tensor.");continue}let xa=C.stackSave(),zt=C.stackAlloc(4*k),Ur=!1,Ke,ut=0;try{C._OrtGetTensorData(wt,zt,zt+k,zt+2*k,zt+3*k)!==0&&se(`Can't access output tensor data on index ${Ee}.`);let hi=k===4?"i32":"i64",Nr=Number(C.getValue(zt,hi));ut=C.getValue(zt+k,"*");let Yi=C.getValue(zt+k*2,"*"),Sa=Number(C.getValue(zt+k*3,hi)),Je=[];for(let Ze=0;Ze<Sa;Ze++)Je.push(Number(C.getValue(Yi+Ze*k,hi)));C._OrtFree(Yi)!==0&&se("Can't free memory for tensor dims.");let At=Je.reduce((Ze,Ge)=>Ze*Ge,1);Ke=ft(Nr);let or=D?.outputPreferredLocations[T[Ee]];if(Ke==="string"){if(or==="gpu-buffer"||or==="ml-tensor")throw new Error("String tensor is not supported on GPU.");let Ze=[];for(let Ge=0;Ge<At;Ge++){let $t=C.getValue(ut+Ge*k,"*"),Ta=C.getValue(ut+(Ge+1)*k,"*"),Ea=Ge===At-1?void 0:Ta-$t;Ze.push(C.UTF8ToString($t,Ea))}bt.push([Ke,Je,Ze,"cpu"])}else if(or==="gpu-buffer"&&At>0){let Ze=C.jsepGetBuffer;if(!Ze)throw new Error('preferredLocation "gpu-buffer" is not supported without using WebGPU.');let Ge=Ze(ut),$t=mt(Nr,At);if($t===void 0||!Or(Ke))throw new Error(`Unsupported data type: ${Ke}`);Ur=!0,bt.push([Ke,Je,{gpuBuffer:Ge,download:C.jsepCreateDownloader(Ge,$t,Ke),dispose:()=>{C._OrtReleaseTensor(wt)!==0&&se("Can't release tensor.")}},"gpu-buffer"])}else if(or==="ml-tensor"&&At>0){let Ze=C.webnnEnsureTensor,Ge=C.webnnIsGraphInputOutputTypeSupported;if(!Ze||!Ge)throw new Error('preferredLocation "ml-tensor" is not supported without using WebNN.');if(mt(Nr,At)===void 0||!Rr(Ke))throw new Error(`Unsupported data type: ${Ke}`);if(!Ge(c,Ke,!1))throw new Error(`preferredLocation "ml-tensor" for ${Ke} output is not supported by current WebNN Context.`);let $t=await Ze(c,ut,Nr,Je,!1);Ur=!0,bt.push([Ke,Je,{mlTensor:$t,download:C.webnnCreateMLTensorDownloader(ut,Ke),dispose:()=>{C.webnnReleaseTensorId(ut),C._OrtReleaseTensor(wt)}},"ml-tensor"])}else if(or==="ml-tensor-cpu-output"&&At>0){let Ze=C.webnnCreateMLTensorDownloader(ut,Ke)(),Ge=bt.length;Ur=!0,Xi.push((async()=>{let $t=[Ge,await Ze];return C.webnnReleaseTensorId(ut),C._OrtReleaseTensor(wt),$t})()),bt.push([Ke,Je,[],"cpu"])}else{let Ze=zr(Ke),Ge=new Ze(At);new Uint8Array(Ge.buffer,Ge.byteOffset,Ge.byteLength).set(C.HEAPU8.subarray(ut,ut+Ge.byteLength)),bt.push([Ke,Je,Ge,"cpu"])}}finally{C.stackRestore(xa),Ke==="string"&&ut&&C._free(ut),Ur||C._OrtReleaseTensor(wt)}}D&&!ee&&(C._OrtClearBoundOutputs(D.handle)!==0&&se("Can't clear bound outputs."),Nt.set(c,[N,V,P,D,ee,!1]));for(let[Ee,wt]of await Promise.all(Xi))bt[Ee][2]=wt;return ot("wasm ProcessOutputTensor"),bt}finally{C.webnnOnRunEnd?.(N),C.stackRestore(it),te.forEach(We=>C._OrtReleaseTensor(We)),Se.forEach(We=>C._OrtReleaseTensor(We)),Z.forEach(We=>C._free(We)),qe!==0&&C._OrtReleaseRunOptions(qe),xe.forEach(We=>C._free(We))}},rr=c=>{let g=ce(),b=Nt.get(c);if(!b)throw new Error("invalid session id");let T=b[0],x=g._OrtEndProfiling(T);x===0&&se("Can't get an profile file name."),g._OrtFree(x)},ri=c=>{let g=[];for(let b of c){let T=b[2];!Array.isArray(T)&&"buffer"in T&&g.push(T.buffer)}return g}}),It,oe,Vt,ir,Qt,ar,Mr,Dr,Ct,qt,ii,ai,ni,Fi,Wi,$a,nr,Gi,ji=I(()=>{Ye(),qi(),ct(),Tr(),It=()=>!!ie.wasm.proxy&&typeof document<"u",Vt=!1,ir=!1,Qt=!1,Dr=new Map,Ct=(c,g)=>{let b=Dr.get(c);b?b.push(g):Dr.set(c,[g])},qt=()=>{if(Vt||!ir||Qt||!oe)throw new Error("worker not ready")},ii=c=>{switch(c.data.type){case"init-wasm":Vt=!1,c.data.err?(Qt=!0,Mr[1](c.data.err)):(ir=!0,Mr[0]()),ar&&(URL.revokeObjectURL(ar),ar=void 0);break;case"init-ep":case"copy-from":case"create":case"release":case"run":case"end-profiling":{let g=Dr.get(c.data.type);c.data.err?g.shift()[1](c.data.err):g.shift()[0](c.data.out);break}}},ai=async()=>{if(!ir){if(Vt)throw new Error("multiple calls to 'initWasm()' detected.");if(Qt)throw new Error("previous call to 'initWasm()' failed.");if(Vt=!0,It())return new Promise((c,g)=>{oe?.terminate(),Ci().then(([b,T])=>{try{oe=T,oe.onerror=O=>g(O),oe.onmessage=ii,Mr=[c,g];let x={type:"init-wasm",in:ie};if(!x.in.wasm.wasmPaths&&b){let O=$r();O&&(x.in.wasm.wasmPaths=O)}oe.postMessage(x),ar=b}catch(x){g(x)}},g)});try{await Ir(ie.wasm),await Xr(ie),ir=!0}catch(c){throw Qt=!0,c}finally{Vt=!1}}},ni=async c=>{if(It())return qt(),new Promise((g,b)=>{Ct("init-ep",[g,b]);let T={type:"init-ep",in:{epName:c,env:ie}};oe.postMessage(T)});await Yr(ie,c)},Fi=async c=>It()?(qt(),new Promise((g,b)=>{Ct("copy-from",[g,b]);let T={type:"copy-from",in:{buffer:c}};oe.postMessage(T,[c.buffer])})):Ae(c),Wi=async(c,g)=>{if(It()){if(g?.preferredOutputLocation)throw new Error('session option "preferredOutputLocation" is not supported for proxy.');return qt(),new Promise((b,T)=>{Ct("create",[b,T]);let x={type:"create",in:{model:c,options:{...g}}},O=[];c instanceof Uint8Array&&O.push(c.buffer),oe.postMessage(x,O)})}else return yt(c,g)},$a=async c=>{if(It())return qt(),new Promise((g,b)=>{Ct("release",[g,b]);let T={type:"release",in:c};oe.postMessage(T)});ti(c)},nr=async(c,g,b,T,x,O)=>{if(It()){if(b.some(C=>C[3]!=="cpu"))throw new Error("input tensor on GPU is not supported for proxy.");if(x.some(C=>C))throw new Error("pre-allocated output tensor is not supported for proxy.");return qt(),new Promise((C,k)=>{Ct("run",[C,k]);let A=b,N={type:"run",in:{sessionId:c,inputIndices:g,inputs:A,outputIndices:T,options:O}};oe.postMessage(N,ri(A))})}else return M(c,g,b,T,x,O)},Gi=async c=>{if(It())return qt(),new Promise((g,b)=>{Ct("end-profiling",[g,b]);let T={type:"end-profiling",in:c};oe.postMessage(T)});rr(c)}}),Hi,si,oi,ui=I(()=>{Ye(),ji(),ue(),wr(),Li(),Hi=(c,g)=>{switch(c.location){case"cpu":return[c.type,c.dims,c.data,"cpu"];case"gpu-buffer":return[c.type,c.dims,{gpuBuffer:c.gpuBuffer},"gpu-buffer"];case"ml-tensor":return[c.type,c.dims,{mlTensor:c.mlTensor},"ml-tensor"];default:throw new Error(`invalid data location: ${c.location} for ${g()}`)}},si=c=>{switch(c[3]){case"cpu":return new je(c[0],c[2],c[1]);case"gpu-buffer":{let g=c[0];if(!Or(g))throw new Error(`not supported data type: ${g} for deserializing GPU tensor`);let{gpuBuffer:b,download:T,dispose:x}=c[2];return je.fromGpuBuffer(b,{dataType:g,dims:c[1],download:T,dispose:x})}case"ml-tensor":{let g=c[0];if(!Rr(g))throw new Error(`not supported data type: ${g} for deserializing MLTensor tensor`);let{mlTensor:b,download:T,dispose:x}=c[2];return je.fromMLTensor(b,{dataType:g,dims:c[1],download:T,dispose:x})}default:throw new Error(`invalid data location: ${c[3]}`)}},oi=class{async fetchModelAndCopyToWasmMemory(c){return Fi(await Br(c))}async loadModel(c,g){tt();let b;typeof c=="string"?b=await this.fetchModelAndCopyToWasmMemory(c):b=c,[this.sessionId,this.inputNames,this.outputNames,this.inputMetadata,this.outputMetadata]=await Wi(b,g),Xe()}async dispose(){return $a(this.sessionId)}async run(c,g,b){tt();let T=[],x=[];Object.entries(c).forEach(P=>{let D=P[0],ee=P[1],z=this.inputNames.indexOf(D);if(z===-1)throw new Error(`invalid input '${D}'`);T.push(ee),x.push(z)});let O=[],C=[];Object.entries(g).forEach(P=>{let D=P[0],ee=P[1],z=this.outputNames.indexOf(D);if(z===-1)throw new Error(`invalid output '${D}'`);O.push(ee),C.push(z)});let k=T.map((P,D)=>Hi(P,()=>`input "${this.inputNames[x[D]]}"`)),A=O.map((P,D)=>P?Hi(P,()=>`output "${this.outputNames[C[D]]}"`):null),N=await nr(this.sessionId,x,k,C,A,b),V={};for(let P=0;P<N.length;P++)V[this.outputNames[C[P]]]=O[P]??si(N[P]);return Xe(),V}startProfiling(){}endProfiling(){Gi(this.sessionId)}}}),Pr={};H(Pr,{OnnxruntimeWebAssemblyBackend:()=>di,initializeFlags:()=>li,wasmBackend:()=>pi});var li,di,pi,Ki=I(()=>{Ye(),ji(),ui(),li=()=>{(typeof ie.wasm.initTimeout!="number"||ie.wasm.initTimeout<0)&&(ie.wasm.initTimeout=0);let c=ie.wasm.simd;if(typeof c!="boolean"&&c!==void 0&&c!=="fixed"&&c!=="relaxed"&&(console.warn(`Property "env.wasm.simd" is set to unknown value "${c}". Reset it to \`false\` and ignore SIMD feature checking.`),ie.wasm.simd=!1),typeof ie.wasm.proxy!="boolean"&&(ie.wasm.proxy=!1),typeof ie.wasm.trace!="boolean"&&(ie.wasm.trace=!1),typeof ie.wasm.numThreads!="number"||!Number.isInteger(ie.wasm.numThreads)||ie.wasm.numThreads<=0)if(typeof self<"u"&&!self.crossOriginIsolated)ie.wasm.numThreads=1;else{let g=typeof navigator>"u"?G("node:os").cpus().length:navigator.hardwareConcurrency;ie.wasm.numThreads=Math.min(4,Math.ceil((g||1)/2))}},di=class{async init(c){li(),await ai(),await ni(c)}async createInferenceSessionHandler(c,g){let b=new oi;return await b.loadModel(c,g),b}},pi=new di}),Zi={};H(Zi,{InferenceSession:()=>yr,TRACE:()=>Ut,TRACE_EVENT_BEGIN:()=>st,TRACE_EVENT_END:()=>ot,TRACE_FUNC_BEGIN:()=>tt,TRACE_FUNC_END:()=>Xe,Tensor:()=>je,default:()=>Ja,env:()=>ie,registerBackend:()=>Q}),Ye(),Ye(),Ye();var va="1.24.3",Ja=$i;{let c=(Ki(),we(Pr)).wasmBackend;Q("cpu",c,10),Q("wasm",c,10)}return Object.defineProperty(ie.versions,"web",{value:va,enumerable:!0}),we(Zi)})();F.exports=Oe})(is)),is.exports}var La=uc();const mh=dh(La),gh=fh({__proto__:null,default:mh},[La]),Gp={"@ricky0123/vad-web":"0.0.31","onnxruntime-web":"1.24.3"};var Jt={},da={},jp;function _a(){if(jp)return da;jp=1,Object.defineProperty(da,"__esModule",{value:!0}),da.log=void 0;const F=ge=>Oe=>{console.log(`VAD | ${ge} >`,Oe)};return da.log={error:F("error"),debug:F("debug"),warn:F("warn")},da}var pa={},Hp;function ba(){if(Hp)return pa;Hp=1,Object.defineProperty(pa,"__esModule",{value:!0}),pa.Message=void 0;var F;return(function(ge){ge.AudioFrame="AUDIO_FRAME",ge.SpeechStart="SPEECH_START",ge.VADMisfire="VAD_MISFIRE",ge.SpeechEnd="SPEECH_END",ge.SpeechStop="SPEECH_STOP",ge.SpeechRealStart="SPEECH_REAL_START",ge.FrameProcessed="FRAME_PROCESSED"})(F||(pa.Message=F={})),pa}var Kp;function Va(){if(Kp)return Jt;Kp=1,Object.defineProperty(Jt,"__esModule",{value:!0}),Jt.FrameProcessor=Jt.validateOptions=Jt.defaultFrameProcessorOptions=void 0;const F=_a(),ge=ba();Jt.defaultFrameProcessorOptions={positiveSpeechThreshold:.3,negativeSpeechThreshold:.25,preSpeechPadMs:800,redemptionMs:1400,minSpeechMs:400,submitUserSpeechOnPause:!1};function Oe(J){(J.positiveSpeechThreshold<0||J.positiveSpeechThreshold>1)&&F.log.error("positiveSpeechThreshold should be a number between 0 and 1"),(J.negativeSpeechThreshold<0||J.negativeSpeechThreshold>J.positiveSpeechThreshold)&&F.log.error("negativeSpeechThreshold should be between 0 and positiveSpeechThreshold"),J.preSpeechPadMs<0&&F.log.error("preSpeechPadMs should be positive"),J.redemptionMs<0&&F.log.error("redemptionMs should be positive"),J.minSpeechMs<0&&F.log.error("minSpeechMs should be positive")}Jt.validateOptions=Oe;const ye=J=>{const G=J.reduce((H,le)=>(H.push(H.at(-1)+le.length),H),[0]),I=new Float32Array(G.at(-1));return J.forEach((H,le)=>{const we=G[le];I.set(H,we)}),I};function ve(J,G){const I=Math.floor(J.redemptionMs/G),H=Math.floor(J.preSpeechPadMs/G),le=Math.floor(J.minSpeechMs/G);return{redemptionFrames:I,preSpeechPadFrames:H,minSpeechFrames:le}}class me{constructor(G,I,H,le){this.modelProcessFunc=G,this.modelResetFunc=I,this.options=H,this.msPerFrame=le,this.speaking=!1,this.redemptionCounter=0,this.speechFrameCount=0,this.active=!1,this.speechRealStartFired=!1,this.setOptions=Q=>{this.options={...this.options,...Q};const{redemptionFrames:Y,preSpeechPadFrames:Ce,minSpeechFrames:Ne}=ve(this.options,this.msPerFrame);this.redemptionFrames=Y,this.preSpeechPadFrames=Ce,this.minSpeechFrames=Ne},this.reset=()=>{this.speaking=!1,this.speechRealStartFired=!1,this.audioBuffer=[],this.modelResetFunc(),this.redemptionCounter=0,this.speechFrameCount=0},this.pause=Q=>{this.active=!1,this.options.submitUserSpeechOnPause?this.endSegment(Q):this.reset()},this.resume=()=>{this.active=!0},this.endSegment=Q=>{const Y=this.audioBuffer;this.audioBuffer=[];const Ce=this.speaking;if(this.reset(),Ce)if(Y.reduce((ze,Te)=>Te.isSpeech?ze+1:ze,0)>=this.minSpeechFrames){const ze=ye(Y.map(Te=>Te.frame));Q({msg:ge.Message.SpeechEnd,audio:ze})}else Q({msg:ge.Message.VADMisfire});return{}},this.process=async(Q,Y)=>{if(!this.active)return;const Ce=await this.modelProcessFunc(Q),Ne=Ce.isSpeech>=this.options.positiveSpeechThreshold;if(Y({probs:Ce,msg:ge.Message.FrameProcessed,frame:Q}),this.audioBuffer.push({frame:Q,isSpeech:Ne}),Ne&&(this.speechFrameCount++,this.redemptionCounter=0),Ne&&!this.speaking&&(this.speaking=!0,Y({msg:ge.Message.SpeechStart})),this.speaking&&this.speechFrameCount===this.minSpeechFrames&&!this.speechRealStartFired&&(this.speechRealStartFired=!0,Y({msg:ge.Message.SpeechRealStart})),Ce.isSpeech<this.options.negativeSpeechThreshold&&this.speaking&&++this.redemptionCounter>=this.redemptionFrames){this.redemptionCounter=0,this.speechFrameCount=0,this.speaking=!1,this.speechRealStartFired=!1;const ze=this.audioBuffer;if(this.audioBuffer=[],ze.reduce((_e,Re)=>Re.isSpeech?_e+1:_e,0)>=this.minSpeechFrames){const _e=ye(ze.map(Re=>Re.frame));Y({msg:ge.Message.SpeechEnd,audio:_e})}else Y({msg:ge.Message.VADMisfire})}if(!this.speaking){for(;this.audioBuffer.length>this.preSpeechPadFrames;)this.audioBuffer.shift();this.speechFrameCount=0}},this.audioBuffer=[];const{redemptionFrames:we,preSpeechPadFrames:he,minSpeechFrames:ne}=ve(this.options,this.msPerFrame);this.redemptionFrames=we,this.preSpeechPadFrames=he,this.minSpeechFrames=ne,this.reset()}}return Jt.FrameProcessor=me,Jt}var yh=Va(),ya=ba(),Kr={},as={},Zp;function wh(){return Zp||(Zp=1,Object.defineProperty(as,"__esModule",{value:!0})),as}var ca={},Qp;function _h(){if(Qp)return ca;Qp=1;var F;Object.defineProperty(ca,"__esModule",{value:!0}),ca.SileroLegacy=void 0;const ge=_a();class Oe{constructor(ve,me,J,G,I){this.ortInstance=ve,this._session=me,this._h=J,this._c=G,this._sr=I,this.reset_state=()=>{const H=Array(128).fill(0);this._h=new this.ortInstance.Tensor("float32",H,[2,1,64]),this._c=new this.ortInstance.Tensor("float32",H,[2,1,64])},this.process=async H=>{const we={input:new this.ortInstance.Tensor("float32",H,[1,H.length]),h:this._h,c:this._c,sr:this._sr},he=await this._session.run(we);this._h=he.hn,this._c=he.cn;const[ne]=he.output?.data;return{notSpeech:1-ne,isSpeech:ne}},this.release=async()=>{await this._session.release(),this._h.dispose(),this._c.dispose(),this._sr.dispose()}}}return ca.SileroLegacy=Oe,F=Oe,Oe.new=async(ye,ve)=>{ge.log.debug("initializing vad");const me=await ve(),J=await ye.InferenceSession.create(me),G=new ye.Tensor("int64",[16000n]),I=Array(128).fill(0),H=new ye.Tensor("float32",I,[2,1,64]),le=new ye.Tensor("float32",I,[2,1,64]);return ge.log.debug("vad is initialized"),new F(ye,J,H,le,G)},ca}var ha={},Xp;function bh(){if(Xp)return ha;Xp=1;var F;Object.defineProperty(ha,"__esModule",{value:!0}),ha.Silero=void 0;const ge=_a(),Oe=64;function ye(me){const J=Array(256).fill(0);return new me.Tensor("float32",J,[2,1,128])}class ve{constructor(J,G,I,H){this._session=J,this._state=G,this._sr=I,this.ortInstance=H,this._context=new Float32Array(Oe),this.reset_state=()=>{this._state=ye(this.ortInstance),this._context=new Float32Array(Oe)},this.process=async le=>{const we=new Float32Array(Oe+le.length);we.set(this._context,0),we.set(le,Oe),this._context=le.slice(-Oe);const ne={input:new this.ortInstance.Tensor("float32",we,[1,we.length]),state:this._state,sr:this._sr},Q=await this._session.run(ne);if(!Q.stateN)throw new Error("No state from model");if(this._state=Q.stateN,!Q.output?.data)throw new Error("No output from model");const Y=Q.output.data[0];if(typeof Y!="number")throw new Error("Weird output data");return{notSpeech:1-Y,isSpeech:Y}},this.release=async()=>{await this._session.release(),this._state.dispose(),this._sr.dispose()}}}return ha.Silero=ve,F=ve,ve.new=async(me,J)=>{ge.log.debug("Loading VAD...");const G=await J(),I=await me.InferenceSession.create(G),H=new me.Tensor("int64",[16000n]),le=ye(me);return ge.log.debug("...finished loading VAD"),new F(I,le,H,me)},ha}var Yp;function us(){return Yp||(Yp=1,(function(F){var ge=Kr&&Kr.__createBinding||(Object.create?(function(me,J,G,I){I===void 0&&(I=G);var H=Object.getOwnPropertyDescriptor(J,G);(!H||("get"in H?!J.__esModule:H.writable||H.configurable))&&(H={enumerable:!0,get:function(){return J[G]}}),Object.defineProperty(me,I,H)}):(function(me,J,G,I){I===void 0&&(I=G),me[I]=J[G]})),Oe=Kr&&Kr.__exportStar||function(me,J){for(var G in me)G!=="default"&&!Object.prototype.hasOwnProperty.call(J,G)&&ge(J,me,G)};Object.defineProperty(F,"__esModule",{value:!0}),F.Silero=F.SileroLegacy=void 0,Oe(wh(),F);var ye=_h();Object.defineProperty(F,"SileroLegacy",{enumerable:!0,get:function(){return ye.SileroLegacy}});var ve=bh();Object.defineProperty(F,"Silero",{enumerable:!0,get:function(){return ve.Silero}})})(Kr)),Kr}var $h=us(),ns={},fa={},Jp;function lc(){if(Jp)return fa;Jp=1,Object.defineProperty(fa,"__esModule",{value:!0}),fa.baseAssetPath=void 0;const ge=typeof window<"u"&&typeof window.document<"u"?window.document.currentScript:null;let Oe="/";return ge&&(Oe=ge.src.replace(/#.*$/,"").replace(/\?.*$/,"").replace(/\/[^/]+$/,"/")),fa.baseAssetPath=Oe,fa}var ma={},ec;function ls(){if(ec)return ma;ec=1,Object.defineProperty(ma,"__esModule",{value:!0}),ma.defaultModelFetcher=void 0;const F=ge=>fetch(ge).then(Oe=>Oe.arrayBuffer());return ma.defaultModelFetcher=F,ma}var er={},ss={exports:{}};var tc;function vh(){return tc||(tc=1,(function(F,ge){var Oe=(()=>{var ye=Object.defineProperty,ve=Object.getOwnPropertyDescriptor,me=Object.getOwnPropertyNames,J=Object.prototype.hasOwnProperty,G=(e=>typeof xt<"u"?xt:typeof Proxy<"u"?new Proxy(e,{get:(t,r)=>(typeof xt<"u"?xt:t)[r]}):e)(function(e){if(typeof xt<"u")return xt.apply(this,arguments);throw Error('Dynamic require of "'+e+'" is not supported')}),I=(e,t)=>()=>(e&&(t=e(e=0)),t),H=(e,t)=>{for(var r in t)ye(e,r,{get:t[r],enumerable:!0})},le=(e,t,r,i)=>{if(t&&typeof t=="object"||typeof t=="function")for(let a of me(t))!J.call(e,a)&&a!==r&&ye(e,a,{get:()=>t[a],enumerable:!(i=ve(t,a))||i.enumerable});return e},we=e=>le(ye({},"__esModule",{value:!0}),e),he,ne,Q,Y,Ce,Ne=I(()=>{he=new Map,ne=[],Q=(e,t,r)=>{if(t&&typeof t.init=="function"&&typeof t.createInferenceSessionHandler=="function"){let i=he.get(e);if(i===void 0)he.set(e,{backend:t,priority:r});else{if(i.priority>r)return;if(i.priority===r&&i.backend!==t)throw new Error(`cannot register backend "${e}" using priority ${r}`)}if(r>=0){let a=ne.indexOf(e);a!==-1&&ne.splice(a,1);for(let n=0;n<ne.length;n++)if(he.get(ne[n]).priority<=r){ne.splice(n,0,e);return}ne.push(e)}return}throw new TypeError("not a valid backend")},Y=async e=>{let t=he.get(e);if(!t)return"backend not found.";if(t.initialized)return t.backend;if(t.aborted)return t.error;{let r=!!t.initPromise;try{return r||(t.initPromise=t.backend.init(e)),await t.initPromise,t.initialized=!0,t.backend}catch(i){return r||(t.error=`${i}`,t.aborted=!0),t.error}finally{delete t.initPromise}}},Ce=async e=>{let t=e.executionProviders||[],r=t.map(u=>typeof u=="string"?u:u.name),i=r.length===0?ne:r,a,n=[],s=new Set;for(let u of i){let l=await Y(u);typeof l=="string"?n.push({name:u,err:l}):(a||(a=l),a===l&&s.add(u))}if(!a)throw new Error(`no available backend found. ERR: ${n.map(u=>`[${u.name}] ${u.err}`).join(", ")}`);for(let{name:u,err:l}of n)r.includes(u)&&console.warn(`removing requested execution provider "${u}" from session options because it is not available: ${l}`);let o=t.filter(u=>s.has(typeof u=="string"?u:u.name));return[a,new Proxy(e,{get:(u,l)=>l==="executionProviders"?o:Reflect.get(u,l)})]}}),ze=I(()=>{Ne()}),Te,_e=I(()=>{Te="1.24.3"}),Re,pe,Fe=I(()=>{_e(),Re="warning",pe={wasm:{},webgl:{},webgpu:{},versions:{common:Te},set logLevel(e){if(e!==void 0){if(typeof e!="string"||["verbose","info","warning","error","fatal"].indexOf(e)===-1)throw new Error(`Unsupported logging level: ${e}`);Re=e}},get logLevel(){return Re}},Object.defineProperty(pe,"logLevel",{enumerable:!0})}),ie,et=I(()=>{Fe(),ie=pe}),lt,St,_t=I(()=>{lt=(e,t)=>{let r=typeof document<"u"?document.createElement("canvas"):new OffscreenCanvas(1,1);r.width=e.dims[3],r.height=e.dims[2];let i=r.getContext("2d");if(i!=null){let a,n;t?.tensorLayout!==void 0&&t.tensorLayout==="NHWC"?(a=e.dims[2],n=e.dims[3]):(a=e.dims[3],n=e.dims[2]);let s=t?.format!==void 0?t.format:"RGB",o=t?.norm,u,l;o===void 0||o.mean===void 0?u=[255,255,255,255]:typeof o.mean=="number"?u=[o.mean,o.mean,o.mean,o.mean]:(u=[o.mean[0],o.mean[1],o.mean[2],0],o.mean[3]!==void 0&&(u[3]=o.mean[3])),o===void 0||o.bias===void 0?l=[0,0,0,0]:typeof o.bias=="number"?l=[o.bias,o.bias,o.bias,o.bias]:(l=[o.bias[0],o.bias[1],o.bias[2],0],o.bias[3]!==void 0&&(l[3]=o.bias[3]));let d=n*a,p=0,h=d,f=d*2,m=-1;s==="RGBA"?(p=0,h=d,f=d*2,m=d*3):s==="RGB"?(p=0,h=d,f=d*2):s==="RBG"&&(p=0,f=d,h=d*2);for(let w=0;w<n;w++)for(let $=0;$<a;$++){let _=(e.data[p++]-l[0])*u[0],y=(e.data[h++]-l[1])*u[1],S=(e.data[f++]-l[2])*u[2],v=m===-1?255:(e.data[m++]-l[3])*u[3];i.fillStyle="rgba("+_+","+y+","+S+","+v+")",i.fillRect($,w,1,1)}if("toDataURL"in r)return r.toDataURL();throw new Error("toDataURL is not supported")}else throw new Error("Can not access image data")},St=(e,t)=>{let r=typeof document<"u"?document.createElement("canvas").getContext("2d"):new OffscreenCanvas(1,1).getContext("2d"),i;if(r!=null){let a,n,s;t?.tensorLayout!==void 0&&t.tensorLayout==="NHWC"?(a=e.dims[2],n=e.dims[1],s=e.dims[3]):(a=e.dims[3],n=e.dims[2],s=e.dims[1]);let o=t!==void 0&&t.format!==void 0?t.format:"RGB",u=t?.norm,l,d;u===void 0||u.mean===void 0?l=[255,255,255,255]:typeof u.mean=="number"?l=[u.mean,u.mean,u.mean,u.mean]:(l=[u.mean[0],u.mean[1],u.mean[2],255],u.mean[3]!==void 0&&(l[3]=u.mean[3])),u===void 0||u.bias===void 0?d=[0,0,0,0]:typeof u.bias=="number"?d=[u.bias,u.bias,u.bias,u.bias]:(d=[u.bias[0],u.bias[1],u.bias[2],0],u.bias[3]!==void 0&&(d[3]=u.bias[3]));let p=n*a;if(t!==void 0&&(t.format!==void 0&&s===4&&t.format!=="RGBA"||s===3&&t.format!=="RGB"&&t.format!=="BGR"))throw new Error("Tensor format doesn't match input tensor dims");let h=4,f=0,m=1,w=2,$=3,_=0,y=p,S=p*2,v=-1;o==="RGBA"?(_=0,y=p,S=p*2,v=p*3):o==="RGB"?(_=0,y=p,S=p*2):o==="RBG"&&(_=0,S=p,y=p*2),i=r.createImageData(a,n);for(let E=0;E<n*a;f+=h,m+=h,w+=h,$+=h,E++)i.data[f]=(e.data[_++]-d[0])*l[0],i.data[m]=(e.data[y++]-d[1])*l[1],i.data[w]=(e.data[S++]-d[2])*l[2],i.data[$]=v===-1?255:(e.data[v++]-d[3])*l[3]}else throw new Error("Can not access image data");return i}}),gt,pr,cr,Ue,jt,hr,Zr=I(()=>{mr(),gt=(e,t)=>{if(e===void 0)throw new Error("Image buffer must be defined");if(t.height===void 0||t.width===void 0)throw new Error("Image height and width must be defined");if(t.tensorLayout==="NHWC")throw new Error("NHWC Tensor layout is not supported yet");let{height:r,width:i}=t,a=t.norm??{mean:255,bias:0},n,s;typeof a.mean=="number"?n=[a.mean,a.mean,a.mean,a.mean]:n=[a.mean[0],a.mean[1],a.mean[2],a.mean[3]??255],typeof a.bias=="number"?s=[a.bias,a.bias,a.bias,a.bias]:s=[a.bias[0],a.bias[1],a.bias[2],a.bias[3]??0];let o=t.format!==void 0?t.format:"RGBA",u=t.tensorFormat!==void 0&&t.tensorFormat!==void 0?t.tensorFormat:"RGB",l=r*i,d=u==="RGBA"?new Float32Array(l*4):new Float32Array(l*3),p=4,h=0,f=1,m=2,w=3,$=0,_=l,y=l*2,S=-1;o==="RGB"&&(p=3,h=0,f=1,m=2,w=-1),u==="RGBA"?S=l*3:u==="RBG"?($=0,y=l,_=l*2):u==="BGR"&&(y=0,_=l,$=l*2);for(let v=0;v<l;v++,h+=p,m+=p,f+=p,w+=p)d[$++]=(e[h]+s[0])/n[0],d[_++]=(e[f]+s[1])/n[1],d[y++]=(e[m]+s[2])/n[2],S!==-1&&w!==-1&&(d[S++]=(e[w]+s[3])/n[3]);return u==="RGBA"?new Le("float32",d,[1,4,r,i]):new Le("float32",d,[1,3,r,i])},pr=async(e,t)=>{let r=typeof HTMLImageElement<"u"&&e instanceof HTMLImageElement,i=typeof ImageData<"u"&&e instanceof ImageData,a=typeof ImageBitmap<"u"&&e instanceof ImageBitmap,n=typeof e=="string",s,o=t??{},u=()=>{if(typeof document<"u")return document.createElement("canvas");if(typeof OffscreenCanvas<"u")return new OffscreenCanvas(1,1);throw new Error("Canvas is not supported")},l=d=>typeof HTMLCanvasElement<"u"&&d instanceof HTMLCanvasElement||d instanceof OffscreenCanvas?d.getContext("2d"):null;if(r){let d=u();d.width=e.width,d.height=e.height;let p=l(d);if(p!=null){let h=e.height,f=e.width;if(t!==void 0&&t.resizedHeight!==void 0&&t.resizedWidth!==void 0&&(h=t.resizedHeight,f=t.resizedWidth),t!==void 0){if(o=t,t.tensorFormat!==void 0)throw new Error("Image input config format must be RGBA for HTMLImageElement");o.tensorFormat="RGBA",o.height=h,o.width=f}else o.tensorFormat="RGBA",o.height=h,o.width=f;p.drawImage(e,0,0),s=p.getImageData(0,0,f,h).data}else throw new Error("Can not access image data")}else if(i){let d,p;if(t!==void 0&&t.resizedWidth!==void 0&&t.resizedHeight!==void 0?(d=t.resizedHeight,p=t.resizedWidth):(d=e.height,p=e.width),t!==void 0&&(o=t),o.format="RGBA",o.height=d,o.width=p,t!==void 0){let h=u();h.width=p,h.height=d;let f=l(h);if(f!=null)f.putImageData(e,0,0),s=f.getImageData(0,0,p,d).data;else throw new Error("Can not access image data")}else s=e.data}else if(a){if(t===void 0)throw new Error("Please provide image config with format for Imagebitmap");let d=u();d.width=e.width,d.height=e.height;let p=l(d);if(p!=null){let h=e.height,f=e.width;return p.drawImage(e,0,0,f,h),s=p.getImageData(0,0,f,h).data,o.height=h,o.width=f,gt(s,o)}else throw new Error("Can not access image data")}else{if(n)return new Promise((d,p)=>{let h=u(),f=l(h);if(!e||!f)return p();let m=new Image;m.crossOrigin="Anonymous",m.src=e,m.onload=()=>{h.width=m.width,h.height=m.height,f.drawImage(m,0,0,h.width,h.height);let w=f.getImageData(0,0,h.width,h.height);o.height=h.height,o.width=h.width,d(gt(w.data,o))}});throw new Error("Input data provided is not supported - aborted tensor creation")}if(s!==void 0)return gt(s,o);throw new Error("Input data provided is not supported - aborted tensor creation")},cr=(e,t)=>{let{width:r,height:i,download:a,dispose:n}=t,s=[1,i,r,4];return new Le({location:"texture",type:"float32",texture:e,dims:s,download:a,dispose:n})},Ue=(e,t)=>{let{dataType:r,dims:i,download:a,dispose:n}=t;return new Le({location:"gpu-buffer",type:r??"float32",gpuBuffer:e,dims:i,download:a,dispose:n})},jt=(e,t)=>{let{dataType:r,dims:i,download:a,dispose:n}=t;return new Le({location:"ml-tensor",type:r??"float32",mlTensor:e,dims:i,download:a,dispose:n})},hr=(e,t,r)=>new Le({location:"cpu-pinned",type:e,data:t,dims:r??[t.length]})}),dt,Tt,fr,mi,qa=I(()=>{dt=new Map([["float32",Float32Array],["uint8",Uint8Array],["int8",Int8Array],["uint16",Uint16Array],["int16",Int16Array],["int32",Int32Array],["bool",Uint8Array],["float64",Float64Array],["uint32",Uint32Array],["int4",Uint8Array],["uint4",Uint8Array]]),Tt=new Map([[Float32Array,"float32"],[Uint8Array,"uint8"],[Int8Array,"int8"],[Uint16Array,"uint16"],[Int16Array,"int16"],[Int32Array,"int32"],[Float64Array,"float64"],[Uint32Array,"uint32"]]),fr=!1,mi=()=>{if(!fr){fr=!0;let e=typeof BigInt64Array<"u"&&BigInt64Array.from,t=typeof BigUint64Array<"u"&&BigUint64Array.from,r=globalThis.Float16Array,i=typeof r<"u"&&r.from;e&&(dt.set("int64",BigInt64Array),Tt.set(BigInt64Array,"int64")),t&&(dt.set("uint64",BigUint64Array),Tt.set(BigUint64Array,"uint64")),i?(dt.set("float16",r),Tt.set(r,"float16")):dt.set("float16",Uint16Array)}}}),gi,yi,Fa=I(()=>{mr(),gi=e=>{let t=1;for(let r=0;r<e.length;r++){let i=e[r];if(typeof i!="number"||!Number.isSafeInteger(i))throw new TypeError(`dims[${r}] must be an integer, got: ${i}`);if(i<0)throw new RangeError(`dims[${r}] must be a non-negative integer, got: ${i}`);t*=i}return t},yi=(e,t)=>{switch(e.location){case"cpu":return new Le(e.type,e.data,t);case"cpu-pinned":return new Le({location:"cpu-pinned",data:e.data,type:e.type,dims:t});case"texture":return new Le({location:"texture",texture:e.texture,type:e.type,dims:t});case"gpu-buffer":return new Le({location:"gpu-buffer",gpuBuffer:e.gpuBuffer,type:e.type,dims:t});case"ml-tensor":return new Le({location:"ml-tensor",mlTensor:e.mlTensor,type:e.type,dims:t});default:throw new Error(`tensorReshape: tensor location ${e.location} is not supported`)}}}),Le,mr=I(()=>{_t(),Zr(),qa(),Fa(),Le=class{constructor(e,t,r){mi();let i,a;if(typeof e=="object"&&"location"in e)switch(this.dataLocation=e.location,i=e.type,a=e.dims,e.location){case"cpu-pinned":{let s=dt.get(i);if(!s)throw new TypeError(`unsupported type "${i}" to create tensor from pinned buffer`);if(!(e.data instanceof s))throw new TypeError(`buffer should be of type ${s.name}`);this.cpuData=e.data;break}case"texture":{if(i!=="float32")throw new TypeError(`unsupported type "${i}" to create tensor from texture`);this.gpuTextureData=e.texture,this.downloader=e.download,this.disposer=e.dispose;break}case"gpu-buffer":{if(i!=="float32"&&i!=="float16"&&i!=="int32"&&i!=="int64"&&i!=="uint32"&&i!=="uint8"&&i!=="bool"&&i!=="uint4"&&i!=="int4")throw new TypeError(`unsupported type "${i}" to create tensor from gpu buffer`);this.gpuBufferData=e.gpuBuffer,this.downloader=e.download,this.disposer=e.dispose;break}case"ml-tensor":{if(i!=="float32"&&i!=="float16"&&i!=="int32"&&i!=="int64"&&i!=="uint32"&&i!=="uint64"&&i!=="int8"&&i!=="uint8"&&i!=="bool"&&i!=="uint4"&&i!=="int4")throw new TypeError(`unsupported type "${i}" to create tensor from MLTensor`);this.mlTensorData=e.mlTensor,this.downloader=e.download,this.disposer=e.dispose;break}default:throw new Error(`Tensor constructor: unsupported location '${this.dataLocation}'`)}else{let s,o;if(typeof e=="string")if(i=e,o=r,e==="string"){if(!Array.isArray(t))throw new TypeError("A string tensor's data must be a string array.");s=t}else{let u=dt.get(e);if(u===void 0)throw new TypeError(`Unsupported tensor type: ${e}.`);if(Array.isArray(t)){if(e==="float16"&&u===Uint16Array||e==="uint4"||e==="int4")throw new TypeError(`Creating a ${e} tensor from number array is not supported. Please use ${u.name} as data.`);e==="uint64"||e==="int64"?s=u.from(t,BigInt):s=u.from(t)}else if(t instanceof u)s=t;else if(t instanceof Uint8ClampedArray)if(e==="uint8")s=Uint8Array.from(t);else throw new TypeError("A Uint8ClampedArray tensor's data must be type of uint8");else if(e==="float16"&&t instanceof Uint16Array&&u!==Uint16Array)s=new globalThis.Float16Array(t.buffer,t.byteOffset,t.length);else throw new TypeError(`A ${i} tensor's data must be type of ${u}`)}else if(o=t,Array.isArray(e)){if(e.length===0)throw new TypeError("Tensor type cannot be inferred from an empty array.");let u=typeof e[0];if(u==="string")i="string",s=e;else if(u==="boolean")i="bool",s=Uint8Array.from(e);else throw new TypeError(`Invalid element type of data array: ${u}.`)}else if(e instanceof Uint8ClampedArray)i="uint8",s=Uint8Array.from(e);else{let u=Tt.get(e.constructor);if(u===void 0)throw new TypeError(`Unsupported type for tensor data: ${e.constructor}.`);i=u,s=e}if(o===void 0)o=[s.length];else if(!Array.isArray(o))throw new TypeError("A tensor's dims must be a number array");a=o,this.cpuData=s,this.dataLocation="cpu"}let n=gi(a);if(this.cpuData&&n!==this.cpuData.length&&!((i==="uint4"||i==="int4")&&Math.ceil(n/2)===this.cpuData.length))throw new Error(`Tensor's size(${n}) does not match data length(${this.cpuData.length}).`);this.type=i,this.dims=a,this.size=n}static async fromImage(e,t){return pr(e,t)}static fromTexture(e,t){return cr(e,t)}static fromGpuBuffer(e,t){return Ue(e,t)}static fromMLTensor(e,t){return jt(e,t)}static fromPinnedBuffer(e,t,r){return hr(e,t,r)}toDataURL(e){return lt(this,e)}toImageData(e){return St(this,e)}get data(){if(this.ensureValid(),!this.cpuData)throw new Error("The data is not on CPU. Use `getData()` to download GPU data to CPU, or use `texture` or `gpuBuffer` property to access the GPU data directly.");return this.cpuData}get location(){return this.dataLocation}get texture(){if(this.ensureValid(),!this.gpuTextureData)throw new Error("The data is not stored as a WebGL texture.");return this.gpuTextureData}get gpuBuffer(){if(this.ensureValid(),!this.gpuBufferData)throw new Error("The data is not stored as a WebGPU buffer.");return this.gpuBufferData}get mlTensor(){if(this.ensureValid(),!this.mlTensorData)throw new Error("The data is not stored as a WebNN MLTensor.");return this.mlTensorData}async getData(e){switch(this.ensureValid(),this.dataLocation){case"cpu":case"cpu-pinned":return this.data;case"texture":case"gpu-buffer":case"ml-tensor":{if(!this.downloader)throw new Error("The current tensor is not created with a specified data downloader.");if(this.isDownloading)throw new Error("The current tensor is being downloaded.");try{this.isDownloading=!0;let t=await this.downloader();return this.downloader=void 0,this.dataLocation="cpu",this.cpuData=t,e&&this.disposer&&(this.disposer(),this.disposer=void 0),t}finally{this.isDownloading=!1}}default:throw new Error(`cannot get data from location: ${this.dataLocation}`)}}dispose(){if(this.isDownloading)throw new Error("The current tensor is being downloaded.");this.disposer&&(this.disposer(),this.disposer=void 0),this.cpuData=void 0,this.gpuTextureData=void 0,this.gpuBufferData=void 0,this.mlTensorData=void 0,this.downloader=void 0,this.isDownloading=void 0,this.dataLocation="none"}ensureValid(){if(this.dataLocation==="none")throw new Error("The tensor is disposed.")}reshape(e){if(this.ensureValid(),this.downloader||this.disposer)throw new Error("Cannot reshape a tensor that owns GPU resource.");return yi(this,e)}}}),je,wi=I(()=>{mr(),je=Le}),Ut,gr,tt,Xe,st,ot,_i=I(()=>{Fe(),Ut=(e,t)=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||console.timeStamp(`${e}::ORT::${t}`)},gr=(e,t)=>{let r=new Error().stack?.split(/\r\n|\r|\n/g)||[],i=!1;for(let a=0;a<r.length;a++){if(i&&!r[a].includes("TRACE_FUNC")){let n=`FUNC_${e}::${r[a].trim().split(" ")[1]}`;t&&(n+=`::${t}`),Ut("CPU",n);return}r[a].includes("TRACE_FUNC")&&(i=!0)}},tt=e=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||gr("BEGIN",e)},Xe=e=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||gr("END",e)},st=e=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||console.time(`ORT::${e}`)},ot=e=>{(typeof pe.trace>"u"?!pe.wasm.trace:!pe.trace)||console.timeEnd(`ORT::${e}`)}}),bi,Wa=I(()=>{Ne(),wi(),_i(),bi=class dc{constructor(t){this.handler=t}async run(t,r,i){tt(),st("InferenceSession.run");let a={},n={};if(typeof t!="object"||t===null||t instanceof je||Array.isArray(t))throw new TypeError("'feeds' must be an object that use input names as keys and OnnxValue as corresponding values.");let s=!0;if(typeof r=="object"){if(r===null)throw new TypeError("Unexpected argument[1]: cannot be null.");if(r instanceof je)throw new TypeError("'fetches' cannot be a Tensor");if(Array.isArray(r)){if(r.length===0)throw new TypeError("'fetches' cannot be an empty array.");s=!1;for(let l of r){if(typeof l!="string")throw new TypeError("'fetches' must be a string array or an object.");if(this.outputNames.indexOf(l)===-1)throw new RangeError(`'fetches' contains invalid output name: ${l}.`);a[l]=null}if(typeof i=="object"&&i!==null)n=i;else if(typeof i<"u")throw new TypeError("'options' must be an object.")}else{let l=!1,d=Object.getOwnPropertyNames(r);for(let p of this.outputNames)if(d.indexOf(p)!==-1){let h=r[p];(h===null||h instanceof je)&&(l=!0,s=!1,a[p]=h)}if(l){if(typeof i=="object"&&i!==null)n=i;else if(typeof i<"u")throw new TypeError("'options' must be an object.")}else n=r}}else if(typeof r<"u")throw new TypeError("Unexpected argument[1]: must be 'fetches' or 'options'.");for(let l of this.inputNames)if(typeof t[l]>"u")throw new Error(`input '${l}' is missing in 'feeds'.`);if(s)for(let l of this.outputNames)a[l]=null;let o=await this.handler.run(t,a,n),u={};for(let l in o)if(Object.hasOwnProperty.call(o,l)){let d=o[l];d instanceof je?u[l]=d:u[l]=new je(d.type,d.data,d.dims)}return ot("InferenceSession.run"),Xe(),u}async release(){return this.handler.dispose()}static async create(t,r,i,a){tt(),st("InferenceSession.create");let n,s={};if(typeof t=="string"){if(n=t,typeof r=="object"&&r!==null)s=r;else if(typeof r<"u")throw new TypeError("'options' must be an object.")}else if(t instanceof Uint8Array){if(n=t,typeof r=="object"&&r!==null)s=r;else if(typeof r<"u")throw new TypeError("'options' must be an object.")}else if(t instanceof ArrayBuffer||typeof SharedArrayBuffer<"u"&&t instanceof SharedArrayBuffer){let d=t,p=0,h=t.byteLength;if(typeof r=="object"&&r!==null)s=r;else if(typeof r=="number"){if(p=r,!Number.isSafeInteger(p))throw new RangeError("'byteOffset' must be an integer.");if(p<0||p>=d.byteLength)throw new RangeError(`'byteOffset' is out of range [0, ${d.byteLength}).`);if(h=t.byteLength-p,typeof i=="number"){if(h=i,!Number.isSafeInteger(h))throw new RangeError("'byteLength' must be an integer.");if(h<=0||p+h>d.byteLength)throw new RangeError(`'byteLength' is out of range (0, ${d.byteLength-p}].`);if(typeof a=="object"&&a!==null)s=a;else if(typeof a<"u")throw new TypeError("'options' must be an object.")}else if(typeof i<"u")throw new TypeError("'byteLength' must be a number.")}else if(typeof r<"u")throw new TypeError("'options' must be an object.");n=new Uint8Array(d,p,h)}else throw new TypeError("Unexpected argument[0]: must be 'path' or 'buffer'.");let[o,u]=await Ce(s),l=await o.createInferenceSessionHandler(n,u);return ot("InferenceSession.create"),Xe(),new dc(l)}startProfiling(){this.handler.startProfiling()}endProfiling(){this.handler.endProfiling()}get inputNames(){return this.handler.inputNames}get outputNames(){return this.handler.outputNames}get inputMetadata(){return this.handler.inputMetadata}get outputMetadata(){return this.handler.outputMetadata}}}),yr,Ga=I(()=>{Wa(),yr=bi}),ja=I(()=>{}),Ha=I(()=>{}),Ka=I(()=>{}),Za=I(()=>{}),$i={};H($i,{InferenceSession:()=>yr,TRACE:()=>Ut,TRACE_EVENT_BEGIN:()=>st,TRACE_EVENT_END:()=>ot,TRACE_FUNC_BEGIN:()=>tt,TRACE_FUNC_END:()=>Xe,Tensor:()=>je,env:()=>ie,registerBackend:()=>Q});var Ye=I(()=>{ze(),et(),Ga(),wi(),ja(),Ha(),_i(),Ka(),Za()}),wr=I(()=>{}),vi={};H(vi,{default:()=>xi});var _r,br,xi,Qa=I(()=>{Cp(),ct(),Tr(),_r="ort-wasm-proxy-worker",br=globalThis.self?.name===_r,br&&(self.onmessage=e=>{let{type:t,in:r}=e.data;try{switch(t){case"init-wasm":Ir(r.wasm).then(()=>{Wn(r).then(()=>{postMessage({type:t})},i=>{postMessage({type:t,err:i})})},i=>{postMessage({type:t,err:i})});break;case"init-ep":{let{epName:i,env:a}=r;Gn(a,i).then(()=>{postMessage({type:t})},n=>{postMessage({type:t,err:n})});break}case"copy-from":{let{buffer:i}=r,a=Da(i);postMessage({type:t,out:a});break}case"create":{let{model:i,options:a}=r;Hn(i,a).then(n=>{postMessage({type:t,out:n})},n=>{postMessage({type:t,err:n})});break}case"release":Kn(r),postMessage({type:t});break;case"run":{let{sessionId:i,inputIndices:a,inputs:n,outputIndices:s,options:o}=r;Qn(i,a,n,s,new Array(s.length).fill(null),o).then(u=>{u.some(l=>l[3]!=="cpu")?postMessage({type:t,err:"Proxy does not support non-cpu tensor location."}):postMessage({type:t,out:u},Yn([...n,...u]))},u=>{postMessage({type:t,err:u})});break}case"end-profiling":Xn(r),postMessage({type:t});break;default:}}catch(i){postMessage({type:t,err:i})}}),xi=br?null:e=>new Worker(e??Ve,{type:"classic",name:_r})}),Si,Ti,Ve,$r,Ht,Ei,ki,vr,Ii,xr,Ci,Sr,zi,Tr=I(()=>{wr(),Si=typeof location>"u"?void 0:location.origin,Ti=()=>typeof document<"u"?document.currentScript?.src:typeof self<"u"?self.location?.href:void 0,Ve=Ti(),$r=()=>{if(Ve&&!Ve.startsWith("blob:"))return Ve.substring(0,Ve.lastIndexOf("/")+1)},Ht=(e,t)=>{try{let r=t??Ve;return(r?new URL(e,r):new URL(e)).origin===Si}catch{return!1}},Ei=(e,t)=>{let r=t??Ve;try{return(r?new URL(e,r):new URL(e)).href}catch{return}},ki=(e,t)=>`${t??"./"}${e}`,vr=async e=>{let t=await(await fetch(e,{credentials:"same-origin"})).blob();return URL.createObjectURL(t)},Ii=async e=>(await import(e)).default,xr=(Qa(),we(vi)).default,Ci=async()=>{if(!Ve)throw new Error("Failed to load proxy worker: cannot determine the script source URL.");if(Ht(Ve))return[void 0,xr()];let e=await vr(Ve);return[e,xr(e)]},Sr=void 0,zi=async(e,t,r,i)=>{let a=Sr&&!(e||t);if(a)if(Ve)a=Ht(Ve)||i&&!r;else if(i&&!r)a=!0;else throw new Error("cannot determine the script source URL.");if(a)return[void 0,Sr];{let n="ort-wasm-simd-threaded.jsep.mjs",s=e??Ei(n,t),o=r&&s&&!Ht(s,t),u=o?await vr(s):s??ki(n,t);return[o?u:void 0,await Ii(u)]}}}),Er,Kt,Et,kr,Ai,Oi,Ri,Ir,ce,ct=I(()=>{Tr(),Kt=!1,Et=!1,kr=!1,Ai=()=>{if(typeof SharedArrayBuffer>"u")return!1;try{return typeof MessageChannel<"u"&&new MessageChannel().port1.postMessage(new SharedArrayBuffer(1)),WebAssembly.validate(new Uint8Array([0,97,115,109,1,0,0,0,1,4,1,96,0,0,3,2,1,0,5,4,1,3,1,1,10,11,1,9,0,65,0,254,16,2,0,26,11]))}catch{return!1}},Oi=()=>{try{return WebAssembly.validate(new Uint8Array([0,97,115,109,1,0,0,0,1,4,1,96,0,0,3,2,1,0,10,30,1,28,0,65,0,253,15,253,12,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,253,186,1,26,11]))}catch{return!1}},Ri=()=>{try{return WebAssembly.validate(new Uint8Array([0,97,115,109,1,0,0,0,1,5,1,96,0,1,123,3,2,1,0,10,19,1,17,0,65,1,253,15,65,2,253,15,65,3,253,15,253,147,2,11]))}catch{return!1}},Ir=async e=>{if(Kt)return Promise.resolve();if(Et)throw new Error("multiple calls to 'initializeWebAssembly()' detected.");if(kr)throw new Error("previous call to 'initializeWebAssembly()' failed.");Et=!0;let t=e.initTimeout,r=e.numThreads;if(e.simd!==!1){if(e.simd==="relaxed"){if(!Ri())throw new Error("Relaxed WebAssembly SIMD is not supported in the current environment.")}else if(!Oi())throw new Error("WebAssembly SIMD is not supported in the current environment.")}let i=Ai();r>1&&!i&&(typeof self<"u"&&!self.crossOriginIsolated&&console.warn("env.wasm.numThreads is set to "+r+", but this will not work unless you enable crossOriginIsolated mode. See https://web.dev/cross-origin-isolation-guide/ for more info."),console.warn("WebAssembly multi-threading is not supported in the current environment. Falling back to single-threading."),e.numThreads=r=1);let a=e.wasmPaths,n=typeof a=="string"?a:void 0,s=a?.mjs,o=s?.href??s,u=a?.wasm,l=u?.href??u,d=e.wasmBinary,[p,h]=await zi(o,n,r>1,!!d||!!l),f=!1,m=[];if(t>0&&m.push(new Promise(w=>{setTimeout(()=>{f=!0,w()},t)})),m.push(new Promise((w,$)=>{let _={numThreads:r};if(d)_.wasmBinary=d,_.locateFile=y=>y;else if(l||n)_.locateFile=y=>l??n+y;else if(o&&o.indexOf("blob:")!==0)_.locateFile=y=>new URL(y,o).href;else if(p){let y=$r();y&&(_.locateFile=S=>y+S)}h(_).then(y=>{Et=!1,Kt=!0,Er=y,w(),p&&URL.revokeObjectURL(p)},y=>{Et=!1,kr=!0,$(y)})})),await Promise.race(m),f)throw new Error(`WebAssembly backend initializing failed due to timeout: ${t}ms`)},ce=()=>{if(Kt&&Er)return Er;throw new Error("WebAssembly is not initialized yet.")}}),He,Zt,se,Cr=I(()=>{ct(),He=(e,t)=>{let r=ce(),i=r.lengthBytesUTF8(e)+1,a=r._malloc(i);return r.stringToUTF8(e,a,i),t.push(a),a},Zt=(e,t,r,i)=>{if(typeof e=="object"&&e!==null){if(r.has(e))throw new Error("Circular reference in options");r.add(e)}Object.entries(e).forEach(([a,n])=>{let s=t?t+a:a;if(typeof n=="object")Zt(n,s+".",r,i);else if(typeof n=="string"||typeof n=="number")i(s,n.toString());else if(typeof n=="boolean")i(s,n?"1":"0");else throw new Error(`Can't handle extra config type: ${typeof n}`)})},se=e=>{let t=ce(),r=t.stackSave();try{let i=t.PTR_SIZE,a=t.stackAlloc(2*i);t._OrtGetLastError(a,a+i);let n=Number(t.getValue(a,i===4?"i32":"i64")),s=t.getValue(a+i,"*"),o=s?t.UTF8ToString(s):"";throw new Error(`${e} ERROR_CODE: ${n}, ERROR_MESSAGE: ${o}`)}finally{t.stackRestore(r)}}}),Bi,Xa=I(()=>{ct(),Cr(),Bi=e=>{let t=ce(),r=0,i=[],a=e||{};try{if(e?.logSeverityLevel===void 0)a.logSeverityLevel=2;else if(typeof e.logSeverityLevel!="number"||!Number.isInteger(e.logSeverityLevel)||e.logSeverityLevel<0||e.logSeverityLevel>4)throw new Error(`log severity level is not valid: ${e.logSeverityLevel}`);if(e?.logVerbosityLevel===void 0)a.logVerbosityLevel=0;else if(typeof e.logVerbosityLevel!="number"||!Number.isInteger(e.logVerbosityLevel))throw new Error(`log verbosity level is not valid: ${e.logVerbosityLevel}`);e?.terminate===void 0&&(a.terminate=!1);let n=0;return e?.tag!==void 0&&(n=He(e.tag,i)),r=t._OrtCreateRunOptions(a.logSeverityLevel,a.logVerbosityLevel,!!a.terminate,n),r===0&&se("Can't create run options."),e?.extra!==void 0&&Zt(e.extra,"",new WeakSet,(s,o)=>{let u=He(s,i),l=He(o,i);t._OrtAddRunConfigEntry(r,u,l)!==0&&se(`Can't set a run config entry: ${s} - ${o}.`)}),[r,i]}catch(n){throw r!==0&&t._OrtReleaseRunOptions(r),i.forEach(s=>t._free(s)),n}}}),Mi,Di,Pi,kt,Ui,Ni,Ya=I(()=>{ct(),Cr(),Mi=e=>{switch(e){case"disabled":return 0;case"basic":return 1;case"extended":return 2;case"layout":return 3;case"all":return 99;default:throw new Error(`unsupported graph optimization level: ${e}`)}},Di=e=>{switch(e){case"sequential":return 0;case"parallel":return 1;default:throw new Error(`unsupported execution mode: ${e}`)}},Pi=e=>{e.extra||(e.extra={}),e.extra.session||(e.extra.session={});let t=e.extra.session;t.use_ort_model_bytes_directly||(t.use_ort_model_bytes_directly="1"),e.executionProviders&&e.executionProviders.some(r=>(typeof r=="string"?r:r.name)==="webgpu")&&(e.enableMemPattern=!1)},kt=(e,t,r,i)=>{let a=He(t,i),n=He(r,i);ce()._OrtAddSessionConfigEntry(e,a,n)!==0&&se(`Can't set a session config entry: ${t} - ${r}.`)},Ui=async(e,t,r)=>{let i=t.executionProviders;for(let a of i){let n=typeof a=="string"?a:a.name,s=[];switch(n){case"webnn":if(n="WEBNN",typeof a!="string"){let p=a?.deviceType;p&&kt(e,"deviceType",p,r)}break;case"webgpu":if(n="JS",typeof a!="string"){let p=a;if(p?.preferredLayout){if(p.preferredLayout!=="NCHW"&&p.preferredLayout!=="NHWC")throw new Error(`preferredLayout must be either 'NCHW' or 'NHWC': ${p.preferredLayout}`);kt(e,"preferredLayout",p.preferredLayout,r)}}break;case"wasm":case"cpu":continue;default:throw new Error(`not supported execution provider: ${n}`)}let o=He(n,r),u=s.length,l=0,d=0;if(u>0){l=ce()._malloc(u*ce().PTR_SIZE),r.push(l),d=ce()._malloc(u*ce().PTR_SIZE),r.push(d);for(let p=0;p<u;p++)ce().setValue(l+p*ce().PTR_SIZE,s[p][0],"*"),ce().setValue(d+p*ce().PTR_SIZE,s[p][1],"*")}await ce()._OrtAppendExecutionProvider(e,o,l,d,u)!==0&&se(`Can't append execution provider: ${n}.`)}},Ni=async e=>{let t=ce(),r=0,i=[],a=e||{};Pi(a);try{let n=Mi(a.graphOptimizationLevel??"all"),s=Di(a.executionMode??"sequential"),o=typeof a.logId=="string"?He(a.logId,i):0,u=a.logSeverityLevel??2;if(!Number.isInteger(u)||u<0||u>4)throw new Error(`log severity level is not valid: ${u}`);let l=a.logVerbosityLevel??0;if(!Number.isInteger(l)||l<0||l>4)throw new Error(`log verbosity level is not valid: ${l}`);let d=typeof a.optimizedModelFilePath=="string"?He(a.optimizedModelFilePath,i):0;if(r=t._OrtCreateSessionOptions(n,!!a.enableCpuMemArena,!!a.enableMemPattern,s,!!a.enableProfiling,0,o,u,l,d),r===0&&se("Can't create session options."),a.executionProviders&&await Ui(r,a,i),a.enableGraphCapture!==void 0){if(typeof a.enableGraphCapture!="boolean")throw new Error(`enableGraphCapture must be a boolean value: ${a.enableGraphCapture}`);kt(r,"enableGraphCapture",a.enableGraphCapture.toString(),i)}if(a.freeDimensionOverrides)for(let[p,h]of Object.entries(a.freeDimensionOverrides)){if(typeof p!="string")throw new Error(`free dimension override name must be a string: ${p}`);if(typeof h!="number"||!Number.isInteger(h)||h<0)throw new Error(`free dimension override value must be a non-negative integer: ${h}`);let f=He(p,i);t._OrtAddFreeDimensionOverride(r,f,h)!==0&&se(`Can't set a free dimension override: ${p} - ${h}.`)}return a.extra!==void 0&&Zt(a.extra,"",new WeakSet,(p,h)=>{kt(r,p,h,i)}),[r,i]}catch(n){throw r!==0&&t._OrtReleaseSessionOptions(r)!==0&&se("Can't release session options."),i.forEach(s=>t._free(s)),n}}}),ht,ft,mt,zr,Ar,Or,Rr,Qr,ue=I(()=>{ht=e=>{switch(e){case"int8":return 3;case"uint8":return 2;case"bool":return 9;case"int16":return 5;case"uint16":return 4;case"int32":return 6;case"uint32":return 12;case"float16":return 10;case"float32":return 1;case"float64":return 11;case"string":return 8;case"int64":return 7;case"uint64":return 13;case"int4":return 22;case"uint4":return 21;default:throw new Error(`unsupported data type: ${e}`)}},ft=e=>{switch(e){case 3:return"int8";case 2:return"uint8";case 9:return"bool";case 5:return"int16";case 4:return"uint16";case 6:return"int32";case 12:return"uint32";case 10:return"float16";case 1:return"float32";case 11:return"float64";case 8:return"string";case 7:return"int64";case 13:return"uint64";case 22:return"int4";case 21:return"uint4";default:throw new Error(`unsupported data type: ${e}`)}},mt=(e,t)=>{let r=[-1,4,1,1,2,2,4,8,-1,1,2,8,4,8,-1,-1,-1,-1,-1,-1,-1,.5,.5][e],i=typeof t=="number"?t:t.reduce((a,n)=>a*n,1);return r>0?Math.ceil(i*r):void 0},zr=e=>{switch(e){case"float16":return typeof Float16Array<"u"&&Float16Array.from?Float16Array:Uint16Array;case"float32":return Float32Array;case"uint8":return Uint8Array;case"int8":return Int8Array;case"uint16":return Uint16Array;case"int16":return Int16Array;case"int32":return Int32Array;case"bool":return Uint8Array;case"float64":return Float64Array;case"uint32":return Uint32Array;case"int64":return BigInt64Array;case"uint64":return BigUint64Array;default:throw new Error(`unsupported type: ${e}`)}},Ar=e=>{switch(e){case"verbose":return 0;case"info":return 1;case"warning":return 2;case"error":return 3;case"fatal":return 4;default:throw new Error(`unsupported logging level: ${e}`)}},Or=e=>e==="float32"||e==="float16"||e==="int32"||e==="int64"||e==="uint32"||e==="uint8"||e==="bool"||e==="uint4"||e==="int4",Rr=e=>e==="float32"||e==="float16"||e==="int32"||e==="int64"||e==="uint32"||e==="uint64"||e==="int8"||e==="uint8"||e==="bool"||e==="uint4"||e==="int4",Qr=e=>{switch(e){case"none":return 0;case"cpu":return 1;case"cpu-pinned":return 2;case"texture":return 3;case"gpu-buffer":return 4;case"ml-tensor":return 5;default:throw new Error(`unsupported data location: ${e}`)}}}),Br,Li=I(()=>{wr(),Br=async e=>{if(typeof e=="string"){let t=await fetch(e);if(!t.ok)throw new Error(`failed to load external data file: ${e}`);let r=t.headers.get("Content-Length"),i=r?parseInt(r,10):0;if(i<1073741824)return new Uint8Array(await t.arrayBuffer());{if(!t.body)throw new Error(`failed to load external data file: ${e}, no response body.`);let a=t.body.getReader(),n;try{n=new ArrayBuffer(i)}catch(o){if(o instanceof RangeError){let u=Math.ceil(i/65536);n=new WebAssembly.Memory({initial:u,maximum:u}).buffer}else throw o}let s=0;for(;;){let{done:o,value:u}=await a.read();if(o)break;let l=u.byteLength;new Uint8Array(n,s,l).set(u),s+=l}return new Uint8Array(n,0,i)}}else return e instanceof Blob?new Uint8Array(await e.arrayBuffer()):e instanceof Uint8Array?e:new Uint8Array(e)}}),Vi,Xr,Yr,Nt,Jr,ei,Ae,yt=I(()=>{ue(),Vi=["V","I","W","E","F"],Xr=(e,t)=>{console.log(`[${Vi[e]},${new Date().toISOString()}]${t}`)},Jr=(e,t)=>{Yr=e,Nt=t},ei=(e,t)=>{let r=Ar(e),i=Ar(Yr);r>=i&&Xr(r,typeof t=="function"?t():t)},Ae=(...e)=>{Nt&&ei(...e)}}),ti,Lt,M,rr,ri,qi,It,oe=I(()=>{ti=class{static calcMatMulShape(e,t){return e[1]!==t[0]?void 0:[e[0],t[1]]}},Lt=class{static calcShape(e,t,r=!1){let i=e.length,a=t.length;if(i===0)return t;if(a===0)return e;let n=Math.max(e.length,t.length),s=new Array(n);if(r){if(i<2||a<2)return;let o=ti.calcMatMulShape([e[i-2],e[i-1]],[t[a-2],t[a-1]]);if(o===void 0)return;[s[n-2],s[n-1]]=o}for(let o=r?3:1;o<=n;o++){let u=i-o<0?1:e[i-o],l=a-o<0?1:t[a-o];if(u!==l&&u>1&&l>1)return;let d=Math.max(u,l);if(u&&l)s[n-o]=Math.max(u,l);else{if(d>1)return;s[n-o]=0}}return s}static isValidBroadcast(e,t){let r=e.length,i=t.length;if(r>i)return!1;for(let a=1;a<=r;a++)if(e[r-a]!==1&&e[r-a]!==t[i-a])return!1;return!0}},M=class Na{static size(t){return Na.getSizeFromDimensionRange(t,0,t.length)}static convertShape(t,r=4){let i=t.length;if(i===0)return[];let a=new Array(i),n=i-1;for(;n>=0;){if(t[n]%r===0){a[n]=t[n]/r;break}if(r%t[n]!==0)throw new Error("cannot convert shape");a[n]=1,r/=t[n],n--}for(n--;n>=0;n--)a[n]=t[n];return a}static sizeFromDimension(t,r){if(r<0||r>t.length)throw new Error(`invalid dimension of ${r} for sizeFromDimension as Tensor has ${t.length} dimensions.`);return Na.getSizeFromDimensionRange(t,r,t.length)}static sizeToDimension(t,r){if(r<0||r>t.length)throw new Error(`invalid dimension of ${r} for sizeToDimension as Tensor has ${t.length} dimensions.`);return Na.getSizeFromDimensionRange(t,0,r)}static getSizeFromDimensionRange(t,r,i){let a=1;for(let n=r;n<i;n++){if(t[n]<0)throw new Error("cannot get valid size from specified dimension range. Most likely the range contains negative values in them.");a*=Number(t[n])}return a}static computeStrides(t){let r=t.length;if(r===0)return[];if(r===1)return[1];let i=new Array(r);i[r-1]=1,i[r-2]=t[r-1];for(let a=r-3;a>=0;--a)i[a]=i[a+1]*t[a+1];return i}static normalizeAxis(t,r){if(t<-r&&t>=r)throw new Error("unsupported axis for this operation.");return t<0?t+r:t}static normalizeAxes(t,r){return t.map(i=>this.normalizeAxis(i,r??t.length))}static sortBasedOnPerm(t,r){return r?r.map(i=>t[i]):t.slice().reverse()}static padShape(t,r){let i=t.length;return t.map((a,n)=>a+r[n]+r[n+i])}static areEqual(t,r){return t.length!==r.length?!1:t.every((i,a)=>i===r[a])}},rr=class wa{static adjustPoolAttributes(t,r,i,a,n,s){if(!t&&i.length!==r.length-2)throw new Error("length of specified kernel shapes should be 2 less than length of input dimensions");if(t)for(let o=0;o<r.length-2;o++)o>=i.length?i.push(r[o+2]):i[o]=r[o+2];for(let o=0;o<i.length;o++)if(o<a.length){if(a[o]<0)throw new Error("strides should be greater than or equal to 1")}else a.push(1);for(let o=0;o<i.length;o++)if(o<n.length){if(n[o]<0)throw new Error("dilations should be greater than or equal to 1")}else n.push(1);for(let o=0;o<i.length*2;o++)if(o<s.length){if(s[o]<0)throw new Error("pad should be greater than or equal to 1")}else s.push(0);for(let o=0;o<i.length;o++){if(i[o]<=0)throw new Error("kernel shapes need to be greater than 0");if(s[o]>=i[o]||s[o+i.length]>=i[o])throw new Error("pads should be smaller than kernel")}}static adjustPadsBasedOnAutoPad(t,r,i,a,n,s,o){if(o){if(n.length!==2*(t.length-2))throw new Error("length of pads should be twice the length of data dimensions");if(r.length!==t.length-2)throw new Error("length of strides should be the length of data dimensions");if(a.length!==t.length-2)throw new Error("length of kernel shapes should be the length of data dimensions");for(let u=0;u<t.length-2;u++)wa.adjustPadAndReturnShape(t[u+(s?1:2)],r[u],i[u],a[u],n,u,u+t.length-2,o)}}static computePoolOutputShape(t,r,i,a,n,s,o){if(r.length<=0)throw new Error("input shape must be of size greater than 0");let u=[r[0],r[1]];return wa.computeShapeHelper(t,r,u,i,a,n,s,o),u}static computeConvOutputShape(t,r,i,a,n,s,o){if(t.length<=0||r.length<=0)throw new Error("invalid input tensor dims or invalid filter tensor dims");let u=[t[0],r[0]];return wa.computeShapeHelper(!1,t,u,i,a,n,s,o),u}static computeShapeHelper(t,r,i,a,n,s,o,u){if(t)for(let l=0;l<r.length-2;l++)i.push(1);else for(let l=0;l<r.length-2;l++)i.push(wa.adjustPadAndReturnShape(r[l+2],a[l],n[l],s[l],o,l,l+r.length-2,u))}static adjustPadAndReturnShape(t,r,i,a,n,s,o,u){let l=i*(a-1)+1;if(u&&u!=="NOTSET")switch(u){case"VALID":return n[s]=0,n[o]=0,Math.floor((t-l)/r+1);case"SAME_LOWER":case"SAME_UPPER":if(i!==1)throw new Error("Dilation not supported for SAME_UPPER or SAME_LOWER");{let d=((t+r-1)/r-1)*r+a-t;return n[s]=Math.floor(u==="SAME_LOWER"?(d+1)/2:d/2),n[o]=d-n[s],Math.floor((t+d-a)/r+1)}default:throw new Error("Unsupported AutoPad type")}else return Math.floor((t+n[s]+n[o]-l)/r+1)}},ri=class{static getShapeOfGemmResult(e,t,r,i,a){if(e.length!==2||r.length!==2)throw new Error("shape need to be of size 2");let n,s,o;t?(n=e[1],s=e[0]):(n=e[0],s=e[1]);let u=-1;if(i?(o=r[0],u=1):(o=r[1],u=0),r[u]!==s)throw new Error("dimension mismatch");if(n<=0||o<=0||s<=0)throw new Error("invalid shape specified");if(a&&!Lt.isValidBroadcast(a,[n,o]))throw new Error("gemm: invalid bias shape for broadcast");return[n,o,s]}},qi=-34028234663852886e22,It=34028234663852886e22}),Vt,ir=I(()=>{ue(),Vt=(e,t)=>new(zr(t))(e)}),Qt,ar,Mr,Dr,Ct,qt,ii,ai,ni,Fi,Wi,$a=I(()=>{ue(),yt(),Qt=new Map([["float32",32],["float16",16],["int32",32],["uint32",32],["int64",64],["uint64",64],["int8",8],["uint8",8],["int4",4],["uint4",4]]),ar=(e,t)=>{if(t==="int32")return e;let r=Qt.get(t);if(!r)throw new Error(`WebNN backend does not support data type: ${t}`);let i=r/8;if(e.byteLength%i!==0)throw new Error(`Invalid Uint8Array length - must be a multiple of ${i}.`);let a=e.byteLength/i,n=new(zr(t))(e.buffer,e.byteOffset,a);switch(t){case"int64":case"uint64":{let s=new Int32Array(a);for(let o=0;o<a;o++){let u=n[o];if(u>2147483647n||u<-2147483648n)throw new Error("Can not convert int64 data to int32 - value out of range.");s[o]=Number(u)}return new Uint8Array(s.buffer)}case"int8":case"uint8":case"uint32":{if(t==="uint32"&&n.some(o=>o>2147483647))throw new Error("Can not convert uint32 data to int32 - value out of range.");let s=Int32Array.from(n,Number);return new Uint8Array(s.buffer)}default:throw new Error(`Unsupported data conversion from ${t} to 'int32'`)}},Mr=(e,t)=>{if(t==="int32")return e;if(e.byteLength%4!==0)throw new Error("Invalid Uint8Array length - must be a multiple of 4 (int32).");let r=e.byteLength/4,i=new Int32Array(e.buffer,e.byteOffset,r);switch(t){case"int64":{let a=BigInt64Array.from(i,BigInt);return new Uint8Array(a.buffer)}case"uint64":{if(i.some(n=>n<0))throw new Error("Can not convert int32 data to uin64 - negative value found.");let a=BigUint64Array.from(i,BigInt);return new Uint8Array(a.buffer)}case"int8":{if(i.some(n=>n<-128||n>127))throw new Error("Can not convert int32 data to int8 - value out of range.");let a=Int8Array.from(i,Number);return new Uint8Array(a.buffer)}case"uint8":{if(i.some(a=>a<0||a>255))throw new Error("Can not convert int32 data to uint8 - value out of range.");return Uint8Array.from(i,Number)}case"uint32":{if(i.some(n=>n<0))throw new Error("Can not convert int32 data to uint32 - negative value found.");let a=Uint32Array.from(i,Number);return new Uint8Array(a.buffer)}default:throw new Error(`Unsupported data conversion from 'int32' to ${t}`)}},Dr=1,Ct=()=>Dr++,qt=new Map([["int8","int32"],["uint8","int32"],["uint32","int32"],["int64","int32"]]),ii=(e,t)=>{let r=Qt.get(e);if(!r)throw new Error(`WebNN backend does not support data type: ${e}`);return t.length>0?Math.ceil(t.reduce((i,a)=>i*a)*r/8):0},ai=class{constructor(e){this.isDataConverted=!1;let{sessionId:t,context:r,tensor:i,dataType:a,shape:n,fallbackDataType:s}=e;this.sessionId=t,this.mlContext=r,this.mlTensor=i,this.dataType=a,this.tensorShape=n,this.fallbackDataType=s}get tensor(){return this.mlTensor}get type(){return this.dataType}get fallbackType(){return this.fallbackDataType}get shape(){return this.tensorShape}get byteLength(){return ii(this.dataType,this.tensorShape)}destroy(){Ae("verbose",()=>"[WebNN] TensorWrapper.destroy"),this.mlTensor.destroy()}write(e){this.mlContext.writeTensor(this.mlTensor,e)}async read(e){if(this.fallbackDataType){let t=await this.mlContext.readTensor(this.mlTensor),r=Mr(new Uint8Array(t),this.dataType);if(e){(e instanceof ArrayBuffer?new Uint8Array(e):new Uint8Array(e.buffer,e.byteOffset,e.byteLength)).set(r);return}else return r.buffer}else return e?this.mlContext.readTensor(this.mlTensor,e):this.mlContext.readTensor(this.mlTensor)}canReuseTensor(e,t,r){return this.mlContext===e&&this.dataType===t&&this.tensorShape.length===r.length&&this.tensorShape.every((i,a)=>i===r[a])}setIsDataConverted(e){this.isDataConverted=e}},ni=class{constructor(e,t){this.tensorManager=e,this.wrapper=t}get tensorWrapper(){return this.wrapper}releaseTensor(){this.tensorWrapper&&(this.tensorManager.releaseTensor(this.tensorWrapper),this.wrapper=void 0)}async ensureTensor(e,t,r,i){let a=this.tensorManager.getMLContext(e),n=this.tensorManager.getMLOpSupportLimits(e),s;if(!n?.input.dataTypes.includes(t)){if(s=qt.get(t),!s||n?.input.dataTypes.includes(s))throw new Error(`WebNN backend does not support data type: ${t}`);Ae("verbose",()=>`[WebNN] TensorIdTracker.ensureTensor: fallback dataType from ${t} to ${s}`)}if(this.wrapper){if(this.wrapper.canReuseTensor(a,t,r))return this.wrapper.tensor;if(i){if(this.wrapper.byteLength!==ii(t,r))throw new Error("Unable to copy data to tensor with different size.");this.activeUpload=new Uint8Array(await this.wrapper.read())}this.tensorManager.releaseTensor(this.wrapper)}let o=typeof MLTensorUsage>"u"?void 0:MLTensorUsage.READ|MLTensorUsage.WRITE;return this.wrapper=await this.tensorManager.getCachedTensor(e,t,r,o,!0,!0,s),i&&this.activeUpload&&(this.wrapper.write(this.activeUpload),this.activeUpload=void 0),this.wrapper.tensor}upload(e){let t=e;if(this.wrapper){if(this.wrapper.fallbackType)if(this.wrapper.fallbackType==="int32")t=ar(e,this.wrapper.type),this.wrapper.setIsDataConverted(!0);else throw new Error(`Unsupported fallback data type: ${this.wrapper.fallbackType}`);if(e.byteLength===this.wrapper.byteLength){this.wrapper.write(t);return}else Ae("verbose",()=>"Data size does not match tensor size. Releasing tensor."),this.releaseTensor()}this.activeUpload?this.activeUpload.set(t):this.activeUpload=new Uint8Array(t)}async download(e){if(this.activeUpload){let t=this.wrapper?.isDataConverted?Mr(this.activeUpload,this.wrapper?.type):this.activeUpload;if(e){e instanceof ArrayBuffer?new Uint8Array(e).set(t):new Uint8Array(e.buffer,e.byteOffset,e.byteLength).set(t);return}else return t.buffer}if(!this.wrapper)throw new Error("Tensor has not been created.");return e?this.wrapper.read(e):this.wrapper.read()}},Fi=class{constructor(e){this.backend=e,this.tensorTrackersById=new Map,this.freeTensors=[],this.externalTensors=new Set}getMLContext(e){let t=this.backend.getMLContext(e);if(!t)throw new Error("MLContext not found for session.");return t}getMLOpSupportLimits(e){return this.backend.getMLOpSupportLimits(e)}reserveTensorId(){let e=Ct();return this.tensorTrackersById.set(e,new ni(this)),e}releaseTensorId(e){let t=this.tensorTrackersById.get(e);t&&(this.tensorTrackersById.delete(e),t.tensorWrapper&&this.releaseTensor(t.tensorWrapper))}async ensureTensor(e,t,r,i,a){Ae("verbose",()=>`[WebNN] TensorManager.ensureTensor {tensorId: ${t}, dataType: ${r}, shape: ${i}, copyOld: ${a}}`);let n=this.tensorTrackersById.get(t);if(!n)throw new Error("Tensor not found.");return n.ensureTensor(e,r,i,a)}upload(e,t){let r=this.tensorTrackersById.get(e);if(!r)throw new Error("Tensor not found.");r.upload(t)}async download(e,t){Ae("verbose",()=>`[WebNN] TensorManager.download {tensorId: ${e}, dstBuffer: ${t?.byteLength}}`);let r=this.tensorTrackersById.get(e);if(!r)throw new Error("Tensor not found.");return r.download(t)}releaseTensorsForSession(e){for(let t of this.freeTensors)t.sessionId===e&&t.destroy();this.freeTensors=this.freeTensors.filter(t=>t.sessionId!==e)}registerTensor(e,t,r,i){let a=this.getMLContext(e),n=Ct(),s=new ai({sessionId:e,context:a,tensor:t,dataType:r,shape:i});return this.tensorTrackersById.set(n,new ni(this,s)),this.externalTensors.add(s),n}async getCachedTensor(e,t,r,i,a,n,s){let o=this.getMLContext(e);for(let[l,d]of this.freeTensors.entries())if(d.canReuseTensor(o,t,r)){Ae("verbose",()=>`[WebNN] Reusing tensor {dataType: ${t}, ${s?`fallbackDataType: ${s},`:""} shape: ${r}`);let p=this.freeTensors.splice(l,1)[0];return p.sessionId=e,p}Ae("verbose",()=>`[WebNN] MLContext.createTensor {dataType: ${t}, ${s?`fallbackDataType: ${s},`:""} shape: ${r}}`);let u=await o.createTensor({dataType:s??t,shape:r,dimensions:r,usage:i,writable:a,readable:n});return new ai({sessionId:e,context:o,tensor:u,dataType:t,shape:r,fallbackDataType:s})}releaseTensor(e){this.externalTensors.has(e)&&this.externalTensors.delete(e),this.freeTensors.push(e)}},Wi=(...e)=>new Fi(...e)}),nr,Gi,ji,Hi=I(()=>{ue(),ct(),ir(),$a(),yt(),nr=new Map([[1,"float32"],[10,"float16"],[6,"int32"],[12,"uint32"],[7,"int64"],[13,"uint64"],[22,"int4"],[21,"uint4"],[3,"int8"],[2,"uint8"],[9,"uint8"]]),Gi=(e,t)=>{if(e===t)return!0;if(e===void 0||t===void 0)return!1;let r=Object.keys(e).sort(),i=Object.keys(t).sort();return r.length===i.length&&r.every((a,n)=>a===i[n]&&e[a]===t[a])},ji=class{constructor(e){this.tensorManager=Wi(this),this.mlContextBySessionId=new Map,this.sessionIdsByMLContext=new Map,this.mlContextCache=[],this.sessionGraphInputs=new Map,this.sessionGraphOutputs=new Map,this.temporaryGraphInputs=[],this.temporaryGraphOutputs=[],this.temporarySessionTensorIds=new Map,this.mlOpSupportLimitsBySessionId=new Map,Jr(e.logLevel,!!e.debug)}get currentSessionId(){if(this.activeSessionId===void 0)throw new Error("No active session");return this.activeSessionId}onRunStart(e){Ae("verbose",()=>`[WebNN] onRunStart {sessionId: ${e}}`),this.activeSessionId=e}onRunEnd(e){Ae("verbose",()=>`[WebNN] onRunEnd {sessionId: ${e}}`);let t=this.temporarySessionTensorIds.get(e);if(t){for(let r of t)Ae("verbose",()=>`[WebNN] releasing temporary tensor {tensorId: ${r}}`),this.tensorManager.releaseTensorId(r);this.temporarySessionTensorIds.delete(e),this.activeSessionId=void 0}}async createMLContext(e){if(e instanceof GPUDevice){let r=this.mlContextCache.findIndex(i=>i.gpuDevice===e);if(r!==-1)return this.mlContextCache[r].mlContext;{let i=await navigator.ml.createContext(e);return this.mlContextCache.push({gpuDevice:e,mlContext:i}),i}}else if(e===void 0){let r=this.mlContextCache.findIndex(i=>i.options===void 0&&i.gpuDevice===void 0);if(r!==-1)return this.mlContextCache[r].mlContext;{let i=await navigator.ml.createContext();return this.mlContextCache.push({mlContext:i}),i}}let t=this.mlContextCache.findIndex(r=>Gi(r.options,e));if(t!==-1)return this.mlContextCache[t].mlContext;{let r=await navigator.ml.createContext(e);return this.mlContextCache.push({options:e,mlContext:r}),r}}registerMLContext(e,t){this.mlContextBySessionId.set(e,t);let r=this.sessionIdsByMLContext.get(t);r||(r=new Set,this.sessionIdsByMLContext.set(t,r)),r.add(e),this.mlOpSupportLimitsBySessionId.has(e)||this.mlOpSupportLimitsBySessionId.set(e,t.opSupportLimits()),this.temporaryGraphInputs.length>0&&(this.sessionGraphInputs.set(e,this.temporaryGraphInputs),this.temporaryGraphInputs=[]),this.temporaryGraphOutputs.length>0&&(this.sessionGraphOutputs.set(e,this.temporaryGraphOutputs),this.temporaryGraphOutputs=[])}onReleaseSession(e){this.sessionGraphInputs.delete(e),this.sessionGraphOutputs.delete(e);let t=this.mlContextBySessionId.get(e);if(!t)return;this.tensorManager.releaseTensorsForSession(e),this.mlContextBySessionId.delete(e),this.mlOpSupportLimitsBySessionId.delete(e);let r=this.sessionIdsByMLContext.get(t);if(r.delete(e),r.size===0){this.sessionIdsByMLContext.delete(t);let i=this.mlContextCache.findIndex(a=>a.mlContext===t);i!==-1&&this.mlContextCache.splice(i,1)}}getMLContext(e){return this.mlContextBySessionId.get(e)}getMLOpSupportLimits(e){return this.mlOpSupportLimitsBySessionId.get(e)}reserveTensorId(){return this.tensorManager.reserveTensorId()}releaseTensorId(e){Ae("verbose",()=>`[WebNN] releaseTensorId {tensorId: ${e}}`),this.tensorManager.releaseTensorId(e)}async ensureTensor(e,t,r,i,a){let n=nr.get(r);if(!n)throw new Error(`Unsupported ONNX data type: ${r}`);return this.tensorManager.ensureTensor(e??this.currentSessionId,t,n,i,a)}async createTemporaryTensor(e,t,r){Ae("verbose",()=>`[WebNN] createTemporaryTensor {onnxDataType: ${t}, shape: ${r}}`);let i=nr.get(t);if(!i)throw new Error(`Unsupported ONNX data type: ${t}`);let a=this.tensorManager.reserveTensorId();await this.tensorManager.ensureTensor(e,a,i,r,!1);let n=this.temporarySessionTensorIds.get(e);return n?n.push(a):this.temporarySessionTensorIds.set(e,[a]),a}uploadTensor(e,t){if(!ce().shouldTransferToMLTensor)throw new Error("Trying to upload to a MLTensor while shouldTransferToMLTensor is false");Ae("verbose",()=>`[WebNN] uploadTensor {tensorId: ${e}, data: ${t.byteLength}}`),this.tensorManager.upload(e,t)}async downloadTensor(e,t){return this.tensorManager.download(e,t)}createMLTensorDownloader(e,t){return async()=>{let r=await this.tensorManager.download(e);return Vt(r,t)}}registerMLTensor(e,t,r,i){let a=nr.get(r);if(!a)throw new Error(`Unsupported ONNX data type: ${r}`);let n=this.tensorManager.registerTensor(e,t,a,i);return Ae("verbose",()=>`[WebNN] registerMLTensor {tensor: ${t}, dataType: ${a}, dimensions: ${i}} -> {tensorId: ${n}}`),n}registerMLConstant(e,t,r,i,a,n,s=!1){if(!n)throw new Error("External mounted files are not available.");let o=e;e.startsWith("./")&&(o=e.substring(2));let u=n.get(o);if(!u)throw new Error(`File with name ${o} not found in preloaded files.`);if(t+r>u.byteLength)throw new Error("Out of bounds: data offset and length exceed the external file data size.");let l=u.slice(t,t+r).buffer,d;switch(a.dataType){case"float32":d=new Float32Array(l);break;case"float16":d=typeof Float16Array<"u"&&Float16Array.from?new Float16Array(l):new Uint16Array(l);break;case"int32":d=new Int32Array(l);break;case"uint32":d=new Uint32Array(l);break;case"int64":if(s){let p=ar(new Uint8Array(l),"int64");d=new Int32Array(p.buffer),a.dataType="int32"}else d=new BigInt64Array(l);break;case"uint64":d=new BigUint64Array(l);break;case"int8":d=new Int8Array(l);break;case"int4":case"uint4":case"uint8":d=new Uint8Array(l);break;default:throw new Error(`Unsupported data type: ${a.dataType} in creating WebNN Constant from external data.`)}return Ae("verbose",()=>`[WebNN] registerMLConstant {dataType: ${a.dataType}, shape: ${a.shape}}} ${s?"(Note: it was int64 data type and registered to int32 as workaround)":""}`),i.constant(a,d)}registerGraphInput(e){this.temporaryGraphInputs.push(e)}registerGraphOutput(e){this.temporaryGraphOutputs.push(e)}isGraphInput(e,t){let r=this.sessionGraphInputs.get(e);return r?r.includes(t):!1}isGraphOutput(e,t){let r=this.sessionGraphOutputs.get(e);return r?r.includes(t):!1}isGraphInputOutputTypeSupported(e,t,r=!0){let i=nr.get(ht(t)),a=this.mlOpSupportLimitsBySessionId.get(e);return typeof i>"u"?!1:r?!!a?.input.dataTypes.includes(i):!!a?.output.dataTypes.includes(i)}flush(){}}}),si=I(()=>{}),oi,ui,Pr,li,di,pi,Ki,Zi,va,Ja=I(()=>{yt(),si(),oi=new Map([[64,250],[128,200],[256,200],[512,200],[2048,230],[4096,200],[8192,50],[16384,50],[32768,50],[65536,50],[131072,50],[262144,50],[524288,50],[1048576,50],[2097152,30],[4194304,20],[8388608,10],[12582912,10],[16777216,10],[26214400,15],[33554432,22],[44236800,2],[58982400,6],[67108864,6],[134217728,6],[167772160,6]]),ui=[],Pr=e=>Math.ceil(Number(e)/16)*16,li=e=>{for(let t=0;t<ui.length;t++){let r=ui[t];if(e<=r)return r}return Math.ceil(e/16)*16},di=1,pi=()=>di++,Ki=async(e,t,r,i)=>{let a=Pr(r),n=e.device.createBuffer({size:a,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});try{let s=e.getCommandEncoder();e.endComputePass(),s.copyBufferToBuffer(t,0,n,0,a),e.flush(),await n.mapAsync(GPUMapMode.READ);let o=n.getMappedRange();if(i){let u=i();return u.set(new Uint8Array(o,0,r)),u}else return new Uint8Array(o.slice(0,r))}finally{n.destroy()}},Zi=class{constructor(e){this.backend=e,this.storageCache=new Map,this.freeBuffers=new Map,this.freeUniformBuffers=new Map,this.buffersPending=[],this.capturedPendingBuffers=new Map;for(let[t]of oi)ui.push(t),this.freeBuffers.set(t,[]),this.freeUniformBuffers.set(t,[]);this.sessionCount=0}upload(e,t){let r=t.buffer,i=t.byteOffset,a=t.byteLength,n=Pr(a),s=this.storageCache.get(e);if(!s)throw new Error("gpu data for uploading does not exist");if(Number(s.originalSize)!==a)throw new Error(`inconsistent data size. gpu data size=${s.originalSize}, data size=${a}`);let o=this.backend.device.createBuffer({mappedAtCreation:!0,size:n,usage:GPUBufferUsage.MAP_WRITE|GPUBufferUsage.COPY_SRC}),u=o.getMappedRange();new Uint8Array(u).set(new Uint8Array(r,i,a)),o.unmap();let l=this.backend.device.createCommandEncoder();l.copyBufferToBuffer(o,0,s.gpuData.buffer,0,n),this.backend.device.queue.submit([l.finish()]),o.destroy(),Ae("verbose",()=>`[WebGPU] GpuDataManager.upload(id=${e})`)}memcpy(e,t){let r=this.storageCache.get(e);if(!r)throw new Error("source gpu data for memcpy does not exist");let i=this.storageCache.get(t);if(!i)throw new Error("destination gpu data for memcpy does not exist");if(r.originalSize!==i.originalSize)throw new Error("inconsistent source and destination gpu data size");let a=Pr(r.originalSize),n=this.backend.getCommandEncoder();this.backend.endComputePass(),n.copyBufferToBuffer(r.gpuData.buffer,0,i.gpuData.buffer,0,a)}registerExternalBuffer(e,t,r){let i;if(r){if(i=r[0],e===r[1])return Ae("verbose",()=>`[WebGPU] GpuDataManager.registerExternalBuffer(size=${t}) => id=${i}, buffer is the same, skip.`),i;if(this.backend.capturedCommandList.has(this.backend.currentSessionId))throw new Error(`Registering a different external buffer under graph capture mode is not supported yet.
             Please use the previous external buffer!`)}else i=pi();return this.storageCache.set(i,{gpuData:{id:i,type:0,buffer:e},originalSize:t}),Ae("verbose",()=>`[WebGPU] GpuDataManager.registerExternalBuffer(size=${t}) => id=${i}, registered.`),i}unregisterExternalBuffer(e){e!==void 0&&(this.storageCache.delete(e),Ae("verbose",()=>`[WebGPU] GpuDataManager.unregisterExternalBuffer() => id=${e}`))}create(e,t=GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_SRC|GPUBufferUsage.COPY_DST){let r=li(e),i,a=(t&GPUBufferUsage.STORAGE)===GPUBufferUsage.STORAGE,n=(t&GPUBufferUsage.UNIFORM)===GPUBufferUsage.UNIFORM;if(a||n){let o=(a?this.freeBuffers:this.freeUniformBuffers).get(r);o?o.length>0?i=o.pop():i=this.backend.device.createBuffer({size:r,usage:t}):i=this.backend.device.createBuffer({size:r,usage:t})}else i=this.backend.device.createBuffer({size:r,usage:t});let s={id:pi(),type:0,buffer:i};return this.storageCache.set(s.id,{gpuData:s,originalSize:Number(e)}),Ae("verbose",()=>`[WebGPU] GpuDataManager.create(size=${e}) => id=${s.id}`),s}get(e){return this.storageCache.get(e)?.gpuData}release(e){let t=typeof e=="bigint"?Number(e):e,r=this.storageCache.get(t);if(!r){if(this.storageCache.size===0)return 0;throw new Error("releasing data does not exist")}return Ae("verbose",()=>`[WebGPU] GpuDataManager.release(id=${t}), gpuDataId=${r.gpuData.id}`),this.storageCache.delete(t),this.buffersPending.push(r.gpuData.buffer),r.originalSize}async download(e,t){let r=this.storageCache.get(Number(e));if(!r)throw new Error("data does not exist");await Ki(this.backend,r.gpuData.buffer,r.originalSize,t)}refreshPendingBuffers(){if(this.buffersPending.length!==0)if(this.backend.sessionStatus==="default"){for(let e of this.buffersPending){let t=oi.get(e.size);if((e.usage&GPUBufferUsage.STORAGE)===GPUBufferUsage.STORAGE){let r=this.freeBuffers.get(e.size)||[];t===void 0||r.length>=t?e.destroy():r.push(e)}else if((e.usage&GPUBufferUsage.UNIFORM)===GPUBufferUsage.UNIFORM){let r=this.freeUniformBuffers.get(e.size)||[];t===void 0||r.length>=t?e.destroy():r.push(e)}else e.destroy()}this.buffersPending=[]}else{let e=this.capturedPendingBuffers.get(this.backend.currentSessionId);e||(e=[],this.capturedPendingBuffers.set(this.backend.currentSessionId,e));for(let t of this.buffersPending)e.push(t);this.buffersPending=[]}}dispose(){this.freeBuffers.forEach(e=>{e.forEach(t=>{t.destroy()})}),this.freeUniformBuffers.forEach(e=>{e.forEach(t=>{t.destroy()})}),this.storageCache.forEach(e=>{e.gpuData.buffer.destroy()}),this.capturedPendingBuffers.forEach(e=>{e.forEach(t=>{t.destroy()})}),this.storageCache=new Map,this.freeBuffers=new Map,this.freeUniformBuffers=new Map,this.capturedPendingBuffers=new Map}onCreateSession(){this.sessionCount+=1}onReleaseSession(e){let t=this.capturedPendingBuffers.get(e);t&&(t.forEach(r=>{r.destroy()}),this.capturedPendingBuffers.delete(e)),this.sessionCount-=1,this.sessionCount===0&&(Ae("warning",()=>"[WebGPU] Clearing webgpu buffer cache"),this.storageCache.forEach(r=>{r.gpuData.buffer.destroy()}),this.storageCache=new Map)}},va=(...e)=>new Zi(...e)}),c,g,b=I(()=>{c=class{constructor(e){Object.assign(this,e)}get cacheKey(){return this.key||(this.key=Object.getOwnPropertyNames(this).sort().map(e=>`${this[e]}`).join(";")),this.key}},g=e=>new c(e)}),T,x,O,C,k,A,N,V,P,D,ee,z,q,qe,xe,te,Se,Z=I(()=>{ue(),oe(),T=64,x=(e,t)=>{if(t===3)throw new Error("vec3 has same alignment as vec4, use vec4 instead");switch(Number(e)){case 10:return t>1?`vec${t}<f16>`:"f16";case 1:return t>1?`vec${t}<f32>`:"f32";case 6:return t>1?`vec${t}<i32>`:"i32";case 12:return t>1?`vec${t}<u32>`:"u32";case 7:if(t>1)throw new Error("currently not supported vecX of uint64 yet");return["vec2<u32>","i32"];case 13:if(t>1)throw new Error("currently not supported vecX of uint64 yet");return["vec2<u32>","u32"];case 9:if(t!==4)throw new Error("bool must be vec4");return["u32","vec4<bool>"];case 22:return"i32";case 21:return"u32";default:throw new Error(`Unknown data type: ${e}`)}},O=(e,t=1)=>{let r=x(e,t);return typeof r=="string"?r:r[0]},C=(e,t=1)=>{let r=x(e,t);return typeof r=="string"?r:r[1]},k=(...e)=>{let t=[];return e.forEach(r=>{r.length!==0&&t.push({type:12,data:r},{type:12,data:M.computeStrides(r)})}),t},A=e=>e%4===0?4:e%2===0?2:1,N=(e="f32",t,r="0")=>!t||t===1?`${e}(${r})`:`vec${t}<${e}>(${r})`,V=(e,t,r)=>e==="f32"?r:t===1?`f32(${r})`:`vec${t}<f32>(${r})`,P=(e,t)=>t===4?`(${e}.x + ${e}.y + ${e}.z + ${e}.w)`:t===2?`(${e}.x + ${e}.y)`:t===3?`(${e}.x + ${e}.y + ${e}.z)`:e,D=(e,t,r,i)=>e.startsWith("uniforms.")&&r>4?typeof t=="string"?i==="f16"?`${e}[(${t}) / 8][(${t}) % 8 / 4][(${t}) % 8 % 4]`:`${e}[(${t}) / 4][(${t}) % 4]`:i==="f16"?`${e}[${Math.floor(t/8)}][${Math.floor(t%8/4)}][${t%8%4}]`:`${e}[${Math.floor(t/4)}][${t%4}]`:r>1?`${e}[${t}]`:e,ee=(e,t,r,i,a)=>{let n=typeof r=="number",s=n?r:r.length,o=[...new Array(s).keys()],u=s<2?"u32":s<=4?`vec${s}<u32>`:`array<u32, ${s}>`,l=x(t,a),d=typeof l=="string"?l:l[1],p=typeof l=="string"?l:l[0],h={indices:u,value:d,storage:p,tensor:t},f=L=>typeof L=="string"?L:`${L}u`,m={offsetToIndices:!1,indicesToOffset:!1,broadcastedIndicesToOffset:!1,set:!1,setByIndices:!1,get:!1,getByIndices:!1},w=n?"uniforms.":"",$=`${w}${e}_shape`,_=`${w}${e}_strides`,y="";for(let L=0;L<s-1;L++)y+=`
    let dim${L} = current / ${D(_,L,s)};
    let rest${L} = current % ${D(_,L,s)};
    indices[${L}] = dim${L};
    current = rest${L};
    `;y+=`indices[${s-1}] = current;`;let S=s<2?"":`
  fn o2i_${e}(offset: u32) -> ${h.indices} {
    var indices: ${h.indices};
    var current = offset;
    ${y}
    return indices;
  }`,v=L=>(m.offsetToIndices=!0,s<2?L:`o2i_${e}(${L})`),E=[];if(s>=2)for(let L=s-1;L>=0;L--)E.push(`${D(_,L,s)} * (indices[${L}])`);let B=s<2?"":`
  fn i2o_${e}(indices: ${h.indices}) -> u32 {
    return ${E.join("+")};
  }`,R=L=>(m.indicesToOffset=!0,s<2?L:`i2o_${e}(${L})`),U=(...L)=>s===0?"0u":`${h.indices}(${L.map(f).join(",")})`,W=(L,K)=>s<2?`${L}`:`${D(L,K,s)}`,X=(L,K,$e)=>s<2?`${L}=${$e};`:`${D(L,K,s)}=${$e};`,ke={},ae=(L,K)=>{m.broadcastedIndicesToOffset=!0;let $e=`${K.name}broadcastedIndicesTo${e}Offset`;if($e in ke)return`${$e}(${L})`;let Pe=[];for(let Dt=s-1;Dt>=0;Dt--){let Gt=K.indicesGet("outputIndices",Dt+K.rank-s);Pe.push(`${W(_,Dt)} * (${Gt} % ${W($,Dt)})`)}return ke[$e]=`fn ${$e}(outputIndices: ${K.type.indices}) -> u32 {
             return ${Pe.length>0?Pe.join("+"):"0u"};
           }`,`${$e}(${L})`},de=(L,K)=>(()=>{if(h.storage===h.value)return`${e}[${L}]=${K};`;if(h.storage==="vec2<u32>"&&h.value==="i32")return`${e}[${L}]=vec2<u32>(u32(${K}), select(0u, 0xFFFFFFFFu, ${K} < 0));`;if(h.storage==="vec2<u32>"&&h.value==="u32")return`${e}[${L}]=vec2<u32>(u32(${K}), 0u);`;if(h.storage==="u32"&&h.value==="vec4<bool>")return`${e}[${L}]=dot(vec4<u32>(0x1, 0x100, 0x10000, 0x1000000), vec4<u32>(${K}));`;throw new Error(`not supported combination of storage type ${h.storage} and value type ${h.value} yet`)})(),Me=L=>(()=>{if(h.storage===h.value)return`${e}[${L}]`;if(h.storage==="vec2<u32>"&&h.value==="i32")return`i32(${e}[${L}].x)`;if(h.storage==="vec2<u32>"&&h.value==="u32")return`u32(${e}[${L}].x)`;if(h.storage==="u32"&&h.value==="vec4<bool>")return`vec4<bool>(bool(${e}[${L}] & 0xFFu), bool(${e}[${L}] & 0xFF00u), bool(${e}[${L}] & 0xFF0000u), bool(${e}[${L}] & 0xFF000000u))`;throw new Error(`not supported combination of storage type ${h.storage} and value type ${h.value} yet`)})(),j=s<2?"":`
  fn get_${e}ByIndices(indices: ${h.indices}) -> ${d} {
    return ${Me(`i2o_${e}(indices)`)};
  }`,re=s<2?"":(()=>{let L=o.map($e=>`d${$e}: u32`).join(", "),K=o.map($e=>`d${$e}`).join(", ");return`
  fn get_${e}(${L}) -> ${d} {
    return get_${e}ByIndices(${U(K)});
  }`})(),Ie=(...L)=>{if(L.length!==s)throw new Error(`indices length must be ${s}`);let K=L.map(f).join(",");return s===0?Me("0u"):s===1?Me(K[0]):(m.get=!0,m.getByIndices=!0,m.indicesToOffset=!0,`get_${e}(${K})`)},be=L=>s<2?Me(L):(m.getByIndices=!0,m.indicesToOffset=!0,`get_${e}ByIndices(${L})`),fe=s<2?"":`
  fn set_${e}ByIndices(indices: ${h.indices}, value: ${d}) {
    ${de(`i2o_${e}(indices)`,"value")}
  }`,De=s<2?"":(()=>{let L=o.map($e=>`d${$e}: u32`).join(", "),K=o.map($e=>`d${$e}`).join(", ");return`
  fn set_${e}(${L}, value: ${d}) {
    set_${e}ByIndices(${U(K)}, value);
  }`})();return{impl:()=>{let L=[],K=!1;return m.offsetToIndices&&(L.push(S),K=!0),m.indicesToOffset&&(L.push(B),K=!0),m.broadcastedIndicesToOffset&&(Object.values(ke).forEach($e=>L.push($e)),K=!0),m.set&&(L.push(De),K=!0),m.setByIndices&&(L.push(fe),K=!0),m.get&&(L.push(re),K=!0),m.getByIndices&&(L.push(j),K=!0),!n&&K&&L.unshift(`const ${$} = ${h.indices}(${r.join(",")});`,`const ${_} = ${h.indices}(${M.computeStrides(r).join(",")});`),L.join(`
`)},type:h,offsetToIndices:v,indicesToOffset:R,broadcastedIndicesToOffset:ae,indices:U,indicesGet:W,indicesSet:X,set:(...L)=>{if(L.length!==s+1)throw new Error(`indices length must be ${s}`);let K=L[s];if(typeof K!="string")throw new Error("value must be string");let $e=L.slice(0,s).map(f).join(",");return s===0?de("0u",K):s===1?de($e[0],K):(m.set=!0,m.setByIndices=!0,m.indicesToOffset=!0,`set_${e}(${$e}, ${K})`)},setByOffset:de,setByIndices:(L,K)=>s<2?de(L,K):(m.setByIndices=!0,m.indicesToOffset=!0,`set_${e}ByIndices(${L}, ${K});`),get:Ie,getByOffset:Me,getByIndices:be,usage:i,name:e,strides:_,shape:$,rank:s}},z=(e,t,r,i=1)=>ee(e,t,r,"input",i),q=(e,t,r,i=1)=>ee(e,t,r,"output",i),qe=(e,t,r)=>ee(e,t,r,"atomicOutput",1),xe=(e,t,r,i=1)=>ee(e,t,r,"internal",i),te=class{constructor(e,t){this.normalizedDispatchGroup=e,this.limits=t,this.internalVariables=[],this.variables=[],this.uniforms=[],this.variableIndex=0}guardAgainstOutOfBoundsWorkgroupSizes(e){return`if (global_idx >= ${typeof e=="number"?`${e}u`:e}) { return; }`}mainStart(e=T){let t=typeof e=="number"?e:e[0],r=typeof e=="number"?1:e[1],i=typeof e=="number"?1:e[2];if(t>this.limits.maxComputeWorkgroupSizeX||r>this.limits.maxComputeWorkgroupSizeY||i>this.limits.maxComputeWorkgroupSizeZ)throw new Error(`workgroup size [${t}, ${r}, ${i}] exceeds the maximum workgroup size [${this.limits.maxComputeWorkgroupSizeX}, ${this.limits.maxComputeWorkgroupSizeY}, ${this.limits.maxComputeWorkgroupSizeZ}].`);if(t*r*i>this.limits.maxComputeInvocationsPerWorkgroup)throw new Error(`workgroup size [${t}, ${r}, ${i}] exceeds the maximum workgroup invocations ${this.limits.maxComputeInvocationsPerWorkgroup}.`);let a=this.normalizedDispatchGroup[1]===1&&this.normalizedDispatchGroup[2]===1,n=a?`@builtin(global_invocation_id) global_id : vec3<u32>,
    @builtin(workgroup_id) workgroup_id : vec3<u32>,
    @builtin(local_invocation_index) local_idx : u32,
    @builtin(local_invocation_id) local_id : vec3<u32>`:`@builtin(global_invocation_id) global_id : vec3<u32>,
                                             @builtin(local_invocation_id) local_id : vec3<u32>,
    @builtin(local_invocation_index) local_idx : u32,
    @builtin(workgroup_id) workgroup_id : vec3<u32>,
    @builtin(num_workgroups) num_workgroups : vec3<u32>`,s=a?`let global_idx = global_id.x;
         let workgroup_index = workgroup_id.x;`:`let workgroup_index = workgroup_id.z * num_workgroups[0] * num_workgroups[1] +
             workgroup_id.y * num_workgroups[0] + workgroup_id.x;
         let global_idx = workgroup_index * ${t*r*i}u + local_idx;`;return`@compute @workgroup_size(${t}, ${r}, ${i})
  fn main(${n}) {
    ${s}
  `}appendVariableUniforms(e){e.rank!==0&&(e.shape.startsWith("uniforms.")&&this.uniforms.push({name:e.shape.replace("uniforms.",""),type:"u32",length:e.rank}),e.strides.startsWith("uniforms.")&&this.uniforms.push({name:e.strides.replace("uniforms.",""),type:"u32",length:e.rank}))}declareVariable(e,t){if(e.usage==="internal")throw new Error("cannot use internal variable with declareVariable(). use registerInternalVariables() instead.");this.variables.push(e),this.appendVariableUniforms(e);let r=e.usage==="input"?"read":"read_write",i=e.usage==="atomicOutput"?"atomic<i32>":e.type.storage;return`@group(0) @binding(${t}) var<storage, ${r}> ${e.name}: array<${i}>;`}declareVariables(...e){return e.map(t=>this.declareVariable(t,this.variableIndex++)).join(`
`)}registerInternalVariable(e){if(e.usage!=="internal")throw new Error("cannot use input or output variable with registerInternalVariable(). use declareVariables() instead.");this.internalVariables.push(e),this.appendVariableUniforms(e)}registerInternalVariables(...e){return e.forEach(t=>this.registerInternalVariable(t)),this}registerUniform(e,t,r=1){return this.uniforms.push({name:e,type:t,length:r}),this}registerUniforms(e){return this.uniforms=this.uniforms.concat(e),this}uniformDeclaration(){if(this.uniforms.length===0)return"";let e=[];for(let{name:t,type:r,length:i}of this.uniforms)if(i&&i>4)r==="f16"?e.push(`@align(16) ${t}:array<mat2x4<${r}>, ${Math.ceil(i/8)}>`):e.push(`${t}:array<vec4<${r}>, ${Math.ceil(i/4)}>`);else{let a=i==null||i===1?r:`vec${i}<${r}>`;e.push(`${t}:${a}`)}return`
      struct Uniforms { ${e.join(", ")} };
      @group(0) @binding(${this.variableIndex}) var<uniform> uniforms: Uniforms;`}get additionalImplementations(){return this.uniformDeclaration()+this.variables.map(e=>e.impl()).join(`
`)+this.internalVariables.map(e=>e.impl()).join(`
`)}get variablesInfo(){if(this.uniforms.length===0)return;let e=t=>[12,10,1,6][["u32","f16","f32","i32"].indexOf(t)];return this.uniforms.map(t=>[e(t.type),t.length??1])}},Se=(e,t)=>new te(e,t)}),rt,it,Ft,sr,ci,Qi,We,bt,Xi,Ee=I(()=>{ue(),oe(),b(),Z(),rt=(e,t)=>{if(!e||e.length!==1)throw new Error("Transpose requires 1 input.");if(t.length!==0&&t.length!==e[0].dims.length)throw new Error(`perm size ${t.length} does not match input rank ${e[0].dims.length}`)},it=(e,t)=>t.length!==0?t:[...new Array(e).keys()].reverse(),Ft=(e,t)=>M.sortBasedOnPerm(e,it(e.length,t)),sr=(e,t,r,i)=>{let a=`fn perm(i: ${i.type.indices}) -> ${r.type.indices} {
    var a: ${r.type.indices};`;for(let n=0;n<t;++n)a+=`a[${e[n]}]=i[${n}];`;return a+="return a;}"},ci=(e,t)=>{let r=[],i=[];for(let a=0;a<e.length;++a)e[a]!==1&&r.push(e[a]),e[t[a]]!==1&&i.push(t[a]);return{newShape:r,newPerm:i}},Qi=(e,t)=>{let r=0;for(let i=0;i<e.length;++i)if(t[e[i]]!==1){if(e[i]<r)return!1;r=e[i]}return!0},We=(e,t)=>{let r=e.dataType,i=e.dims.length,a=it(i,t),n=Ft(e.dims,a),s=e.dims,o=n,u=i<2||Qi(a,e.dims),l;if(u)return l=m=>{let w=z("input",r,s,4),$=q("output",r,o,4);return`
  ${m.registerUniform("output_size","u32").declareVariables(w,$)}
  ${m.mainStart()}
    ${m.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
    output[global_idx] = input[global_idx];
  }`},{name:"TransposeCopy",shaderCache:{inputDependencies:["type"]},getRunData:()=>{let m=M.size(n);return{outputs:[{dims:n,dataType:e.dataType}],dispatchGroup:{x:Math.ceil(m/64/4)},programUniforms:[{type:12,data:Math.ceil(m/4)}]}},getShaderSource:l};let{newShape:d,newPerm:p}=ci(e.dims,a),h=M.areEqual(p,[2,3,1]),f=M.areEqual(p,[3,1,2]);if(d.length===2||h||f){s=h?[d[0],d[1]*d[2]]:f?[d[0]*d[1],d[2]]:d,o=[s[1],s[0]];let m=16;return l=w=>{let $=z("a",r,s.length),_=q("output",r,o.length);return`
  ${w.registerUniform("output_size","u32").declareVariables($,_)}
  var<workgroup> tile : array<array<${_.type.value}, ${m+1}>, ${m}>;
  ${w.mainStart([m,m,1])}
    let stride = (uniforms.output_shape[1] - 1) / ${m} + 1;
    let workgroup_id_x = workgroup_index % stride;
    let workgroup_id_y = workgroup_index / stride;
    let input_col = workgroup_id_y * ${m}u + local_id.x;
    let input_row = workgroup_id_x * ${m}u + local_id.y;
    if (input_row < uniforms.a_shape[0] && input_col < uniforms.a_shape[1]) {
      tile[local_id.y][local_id.x] = ${$.getByIndices(`${$.type.indices}(input_row, input_col)`)};
    }
    workgroupBarrier();

    let output_col = workgroup_id_x * ${m}u + local_id.x;
    let output_row = workgroup_id_y * ${m}u + local_id.y;
    if (output_row < uniforms.output_shape[0] && output_col < uniforms.output_shape[1]) {
      ${_.setByIndices(`${_.type.indices}(output_row, output_col)`,"tile[local_id.x][local_id.y]")}
    }
  }`},{name:"TransposeShared",shaderCache:{inputDependencies:["type"]},getRunData:()=>{let w=M.size(n);return{outputs:[{dims:n,dataType:e.dataType}],dispatchGroup:{x:Math.ceil(o[1]/m),y:Math.ceil(o[0]/m)},programUniforms:[{type:12,data:w},...k(s,o)]}},getShaderSource:l}}return l=m=>{let w=z("a",r,s.length),$=q("output",r,o.length);return`
  ${m.registerUniform("output_size","u32").declareVariables(w,$)}

  ${sr(a,i,w,$)}

  ${m.mainStart()}
    ${m.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}

    let indices = ${$.offsetToIndices("global_idx")};
    let aIndices = perm(indices);

    ${$.setByOffset("global_idx",w.getByIndices("aIndices"))}
  }`},{name:"Transpose",shaderCache:{hint:`${t}`,inputDependencies:["rank"]},getRunData:()=>{let m=M.size(n);return{outputs:[{dims:n,dataType:e.dataType}],dispatchGroup:{x:Math.ceil(m/64)},programUniforms:[{type:12,data:m},...k(s,o)]}},getShaderSource:l}},bt=(e,t)=>{rt(e.inputs,t.perm),e.compute(We(e.inputs[0],t.perm))},Xi=e=>g({perm:e.perm})}),wt,xa,zt,Ur,Ke,ut,hi,Nr,Yi,Sa,Je,At,or,Ze,Ge,$t,Ta,Ea,ds,ps,cs,hc=I(()=>{ue(),oe(),Z(),tn(),Ee(),wt={max:"select(bestValue, candidate, candidate > bestValue)",min:"select(bestValue, candidate, candidate < bestValue)",mean:"bestValue + candidate",sum:"bestValue + candidate",prod:"bestValue * candidate",sumSquare:"bestValue + candidate * candidate",logSumExp:"bestValue + exp(candidate)",l1:"bestValue + abs(candidate)",l2:"bestValue + candidate * candidate",logSum:"bestValue + candidate"},xa={max:"select(bestValue, candidate, candidate > bestValue)",min:"select(bestValue, candidate, candidate < bestValue)",mean:"bestValue + candidate",sum:"bestValue + candidate",prod:"bestValue * candidate",sumSquare:"bestValue + candidate",logSumExp:"bestValue + candidate",l1:"bestValue + candidate",l2:"bestValue + candidate",logSum:"bestValue + candidate"},zt={max:"_A[offset]",min:"_A[offset]",mean:"0",sum:"0",prod:"1",sumSquare:"0",logSumExp:"0",l1:"0",l2:"0",logSum:"0"},Ur={max:"bestValue",min:"bestValue",sum:"bestValue",prod:"bestValue",sumSquare:"bestValue",logSumExp:"log(bestValue)",l1:"bestValue",l2:"sqrt(bestValue)",logSum:"log(bestValue)"},Ke=(e,t)=>{let r=[];for(let i=t-e;i<t;++i)r.push(i);return r},ut=(e,t)=>{let r=[],i=e.length;for(let n=0;n<i;n++)t.indexOf(n)===-1&&r.push(e[n]);let a=t.map(n=>e[n]);return[r,a]},hi=(e,t)=>{let r=e.length+t.length,i=[],a=0;for(let n=0;n<r;n++)t.indexOf(n)===-1?i.push(e[a++]):i.push(1);return i},Nr=(e,t)=>{for(let r=0;r<e.length;++r)if(e[e.length-r-1]!==t-1-r)return!1;return!0},Yi=(e,t)=>{let r=[];if(!Nr(e,t)){for(let i=0;i<t;++i)e.indexOf(i)===-1&&r.push(i);e.forEach(i=>r.push(i))}return r},Sa=(e,t,r,i,a,n,s)=>{let o=r[0].dims,u=M.size(n),l=M.size(s),d=z("_A",r[0].dataType,o),p=q("output",a,n),h=64;u===1&&(h=256);let f=`
          var<workgroup> aBestValues : array<f32, ${h}>;
       `,m=w=>`
        ${w.registerUniform("reduceSize","u32").declareVariables(d,p)}
        ${f}
        fn DIV_CEIL(a : u32, b : u32) -> u32 {
          return ((a - 1u) / b + 1u);
         }
         ${w.mainStart(h)}

          let outputIndex = global_idx / ${h};
          let offset = outputIndex * uniforms.reduceSize;

          var bestValue = f32(${zt[i]});
          let Length = uniforms.reduceSize;
          for (var k = local_idx; k < Length; k = k + ${h}) {
           let candidate = f32(${d.getByOffset("offset + k")});
           bestValue = ${wt[i]};
          }
          aBestValues[local_idx] = bestValue;
          workgroupBarrier();

         var reduceSize = min(Length, ${h}u);
         for (var currentSize = reduceSize / 2u; reduceSize > 1u;
             currentSize = reduceSize / 2u) {
           let interval = DIV_CEIL(reduceSize, 2u);
           if (local_idx < currentSize) {
            let candidate = aBestValues[local_idx + interval];
            bestValue = ${xa[i]};
            aBestValues[local_idx] = bestValue;
           }
           reduceSize = interval;
           workgroupBarrier();
         }

         if (local_idx == 0u) {
          ${p.setByOffset("outputIndex",`${i==="mean"?`${p.type.storage}(bestValue / f32(uniforms.reduceSize))`:`${p.type.storage}(${Ur[i]})`}`)};
         }
        }`;return{name:e,shaderCache:{hint:`${t};${h}`,inputDependencies:["type"]},getShaderSource:m,getRunData:()=>({outputs:[{dims:n,dataType:a}],dispatchGroup:{x:u},programUniforms:[{type:12,data:l}]})}},Je=(e,t,r,i)=>{let a=e.inputs.length===1?r:en(e.inputs,r),n=a.axes;n.length===0&&!a.noopWithEmptyAxes&&(n=e.inputs[0].dims.map((f,m)=>m));let s=M.normalizeAxes(n,e.inputs[0].dims.length),o=s,u=e.inputs[0],l=Yi(o,e.inputs[0].dims.length);l.length>0&&(u=e.compute(We(e.inputs[0],l),{inputs:[0],outputs:[-1]})[0],o=Ke(o.length,u.dims.length));let[d,p]=ut(u.dims,o),h=d;a.keepDims&&(h=hi(d,s)),e.compute(Sa(t,a.cacheKey,[u],i,e.inputs[0].dataType,h,p),{inputs:[u]})},At=(e,t)=>{Je(e,"ReduceMeanShared",t,"mean")},or=(e,t)=>{Je(e,"ReduceL1Shared",t,"l1")},Ze=(e,t)=>{Je(e,"ReduceL2Shared",t,"l2")},Ge=(e,t)=>{Je(e,"ReduceLogSumExpShared",t,"logSumExp")},$t=(e,t)=>{Je(e,"ReduceMaxShared",t,"max")},Ta=(e,t)=>{Je(e,"ReduceMinShared",t,"min")},Ea=(e,t)=>{Je(e,"ReduceProdShared",t,"prod")},ds=(e,t)=>{Je(e,"ReduceSumShared",t,"sum")},ps=(e,t)=>{Je(e,"ReduceSumSquareShared",t,"sumSquare")},cs=(e,t)=>{Je(e,"ReduceLogSumShared",t,"logSum")}}),Ot,hs,ka,en,Rt,fs,ms,gs,ys,ws,_s,bs,$s,vs,xs,Bt,Ss,Ts,Es,ks,Is,Cs,zs,As,Os,Rs,tn=I(()=>{ue(),oe(),b(),Z(),hc(),Ot=e=>{if(!e||e.length===0||e.length>2)throw new Error("Reduce op requires 1 or 2 inputs.");if(e.length===2&&e[1].dims.length!==1)throw new Error("Invalid axes input dims.")},hs=e=>["","",`var value = ${e.getByIndices("input_indices")};`,""],ka=(e,t,r,i,a,n,s=!1,o=!1)=>{let u=[],l=r[0].dims,d=l.length,p=M.normalizeAxes(a,d),h=!o&&p.length===0;l.forEach((w,$)=>{h||p.indexOf($)>=0?s&&u.push(1):u.push(w)});let f=u.length,m=M.size(u);return{name:e,shaderCache:t,getShaderSource:w=>{let $=[],_=z("_A",r[0].dataType,d),y=q("output",n,f),S=i(_,y,p),v=S[2];for(let E=0,B=0;E<d;E++)h||p.indexOf(E)>=0?(s&&B++,v=`for(var j${E}: u32 = 0; j${E} < ${l[E]}; j${E}++) {
                  ${S[2].includes("last_index")?`let last_index = j${E};`:""}
                  ${_.indicesSet("input_indices",E,`j${E}`)}
                  ${v}
                }`):($.push(`${_.indicesSet("input_indices",E,y.indicesGet("output_indices",B))};`),B++);return`

        ${w.registerUniform("output_size","u32").declareVariables(_,y)}

        ${w.mainStart()}
          ${w.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
          var input_indices: ${_.type.indices};
          let output_indices = ${y.offsetToIndices("global_idx")};

          ${$.join(`
`)}
          ${S[0]}       // init ops for reduce max/min
          ${S[1]}
          ${v}
          ${S[3]}
          ${S.length===4?y.setByOffset("global_idx","value"):S.slice(4).join(`
`)}
        }`},getRunData:()=>({outputs:[{dims:u,dataType:n}],dispatchGroup:{x:Math.ceil(m/64)},programUniforms:[{type:12,data:m},...k(l,u)]})}},en=(e,t)=>{let r=[];return e[1].dims[0]>0&&e[1].getBigInt64Array().forEach(i=>r.push(Number(i))),g({axes:r,keepDims:t.keepDims,noopWithEmptyAxes:t.noopWithEmptyAxes})},Rt=(e,t,r,i)=>{let a=e.inputs,n=a.length===1?r:en(a,r);e.compute(ka(t,{hint:n.cacheKey,inputDependencies:["rank"]},[a[0]],n.noopWithEmptyAxes&&n.axes.length===0?hs:i,n.axes,a[0].dataType,n.keepDims,n.noopWithEmptyAxes),{inputs:[0]})},fs=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceLogSum",t,(r,i)=>[`var value = ${i.type.storage}(0);`,"",`value += ${r.getByIndices("input_indices")};`,"value = log(value);"])},ms=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceL1",t,(r,i)=>[`var value = ${i.type.storage}(0);`,"",`value += abs(${r.getByIndices("input_indices")});`,""])},gs=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceL2",t,(r,i)=>[`var t = ${i.type.value}(0); var value = ${i.type.value}(0);`,"",`t = ${r.getByIndices("input_indices")}; value += (t * t);`,"value = sqrt(value);"])},ys=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceLogSumExp",t,(r,i)=>[`var value = ${i.type.storage}(0);`,"",`value += exp(${r.getByIndices("input_indices")});`,"value = log(value);"])},ws=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceMax",t,(r,i,a)=>{let n=[];for(let s=0;s<r.rank;s++)(a.indexOf(s)>=0||a.length===0)&&n.push(r.indicesSet("input_indices",s,0));return[`${n.join(`
`)}`,`var value = ${r.getByIndices("input_indices")};`,`value = max(value, ${r.getByIndices("input_indices")});`,""]})},_s=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceMean",t,(r,i,a)=>{let n=1;for(let s=0;s<r.rank;s++)(a.indexOf(s)>=0||a.length===0)&&(n*=e.inputs[0].dims[s]);return["var sum = f32(0);","",`sum += f32(${r.getByIndices("input_indices")});`,`let value = ${i.type.value}(sum / ${n});`]})},bs=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceMin",t,(r,i,a)=>{let n=[];for(let s=0;s<r.rank;s++)(a.indexOf(s)>=0||a.length===0)&&n.push(`input_indices[${s}] = 0;`);return[`${n.join(`
`)}`,`var value = ${r.getByIndices("input_indices")};`,`value = min(value, ${r.getByIndices("input_indices")});`,""]})},$s=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceProd",t,(r,i)=>[`var value = ${i.type.storage}(1);`,"",`value *= ${r.getByIndices("input_indices")};`,""])},vs=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceSum",t,(r,i)=>[`var value = ${i.type.storage}(0);`,"",`value += ${r.getByIndices("input_indices")};`,""])},xs=(e,t)=>{Ot(e.inputs),Rt(e,"ReduceSumSquare",t,(r,i)=>[`var t = ${i.type.value}(0); var value = ${i.type.value}(0);`,"",`t = ${r.getByIndices("input_indices")}; value += t * t;`,""])},Bt=(e,t,r)=>{if(t.length===0)return r;let i=1,a=1;for(let n=0;n<t.length;n++)t.indexOf(n)===-1?i*=e[n]:a*=e[n];return a<32&&i>1024},Ss=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?_s(e,t):At(e,t)},Ts=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?ms(e,t):or(e,t)},Es=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?gs(e,t):Ze(e,t)},ks=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?ys(e,t):Ge(e,t)},Is=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?ws(e,t):$t(e,t)},Cs=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?bs(e,t):Ta(e,t)},zs=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?$s(e,t):Ea(e,t)},As=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?vs(e,t):ds(e,t)},Os=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?xs(e,t):ps(e,t)},Rs=(e,t)=>{Bt(e.inputs[0].dims,t.axes,t.noopWithEmptyAxes)?fs(e,t):cs(e,t)}}),rn,Bs,Ms,an,fc=I(()=>{ue(),b(),tn(),rn=e=>{if(!e||e.length===0||e.length>2)throw new Error("ArgMinMaxOp op requires 1 or 2 inputs.");if(e[0].dataType!==1)throw new Error("Invalid input type.")},Bs=(e,t)=>{rn(e.inputs);let r=(i,a,n)=>{let s=[];for(let o=0;o<i.rank;o++)(n.indexOf(o)>=0||n.length===0)&&s.push(`input_indices[${o}] = 0;`);return[`${s.join(`
`)}`,`var value = ${i.getByIndices("input_indices")};
var best_index : i32 = 0;`,`if (${i.getByIndices("input_indices")} ${t.selectLastIndex>0?"<=":"<"} value) {
         value = ${i.getByIndices("input_indices")};
         best_index = i32(last_index);
       }`,"",a.setByOffset("global_idx","best_index")]};e.compute(ka("ArgMin",{hint:t.cacheKey,inputDependencies:["rank"]},[e.inputs[0]],r,[t.axis],7,t.keepDims),{inputs:[0]})},Ms=(e,t)=>{rn(e.inputs);let r=(i,a,n)=>{let s=[];for(let o=0;o<i.rank;o++)(n.indexOf(o)>=0||n.length===0)&&s.push(`input_indices[${o}] = 0;`);return[`${s.join(`
`)}`,`var value = ${i.getByIndices("input_indices")};
var best_index : i32 = 0;`,`if (${i.getByIndices("input_indices")} ${t.selectLastIndex>0?">=":">"} value) {
         value = ${i.getByIndices("input_indices")};
         best_index = i32(last_index);
       }`,"",a.setByOffset("global_idx","best_index")]};e.compute(ka("argMax",{hint:t.cacheKey,inputDependencies:["rank"]},[e.inputs[0]],r,[t.axis],7,t.keepDims),{inputs:[0]})},an=e=>g(e)}),Ds,Ia,Ps,Us,Ns,Ji,Ls,Vs,nn=I(()=>{ue(),oe(),si(),Z(),Ds=(e,t)=>{let r=e[0],i=e[1],a=e[2],n=e[3],s=e[4],o=e[5];if(s&&o)throw new Error("Attention cannot have both past and attention_bias");if(r.dims.length!==3)throw new Error('Input "input" must have 3 dimensions');let u=r.dims[0],l=r.dims[1],d=r.dims[2];if(a.dims.length!==1)throw new Error('Input "bias" is expected to have 1 dimensions');if(i.dims.length!==2)throw new Error('Input "weights" is expected to have 2 dimensions');if(i.dims[0]!==d)throw new Error("Input 1 dimension 0 should have same length as dimension 2 of input 0");if(a.dims[0]!==i.dims[1])throw new Error('Input "bias" dimension 0 should have same length as dimension 1 of input "weights"');let p=a.dims[0]/3,h=p,f=h;if(t.qkvHiddenSizes.length>0){if(t.qkvHiddenSizes.length!==3)throw new Error("qkv_hidden_sizes attribute should have 3 elements");for(let S of t.qkvHiddenSizes)if(S%t.numHeads!==0)throw new Error("qkv_hidden_sizes should be divisible by num_heads");p=t.qkvHiddenSizes[0],h=t.qkvHiddenSizes[1],f=t.qkvHiddenSizes[2]}let m=l;if(p!==h)throw new Error("qkv_hidden_sizes first element should be same as the second");if(a.dims[0]!==p+h+f)throw new Error('Input "bias" dimension 0 should have same length as sum of Q/K/V hidden sizes');let w=0;if(s){if(h!==f)throw new Error('Input "past" expect k_hidden_size == v_hidden_size');if(s.dims.length!==5)throw new Error('Input "past" must have 5 dimensions');if(s.dims[0]!==2)throw new Error('Input "past" first dimension must be 2');if(s.dims[1]!==u)throw new Error('Input "past" second dimension must be batch_size');if(s.dims[2]!==t.numHeads)throw new Error('Input "past" third dimension must be num_heads');if(s.dims[4]!==h/t.numHeads)throw new Error('Input "past" fifth dimension must be k_hidden_size / num_heads');t.pastPresentShareBuffer||(w=s.dims[3])}let $=m+w,_=-1,y=0;if(n)throw new Error("Mask not supported");if(s)throw new Error("past is not supported");if(o){if(o.dims.length!==4)throw new Error('Input "attention_bias" must have 4 dimensions');if(o.dims[0]!==u||o.dims[1]!==t.numHeads||o.dims[2]!==l||o.dims[3]!==$)throw new Error('Expect "attention_bias" shape (batch_size, num_heads, sequence_length, total_sequence_length)')}return{batchSize:u,sequenceLength:l,pastSequenceLength:w,kvSequenceLength:m,totalSequenceLength:$,maxSequenceLength:_,inputHiddenSize:d,hiddenSize:p,vHiddenSize:f,headSize:Math.floor(p/t.numHeads),vHeadSize:Math.floor(f/t.numHeads),numHeads:t.numHeads,isUnidirectional:!1,pastPresentShareBuffer:!1,maskFilterValue:t.maskFilterValue,maskType:y,scale:t.scale,broadcastResPosBias:!1,passPastInKv:!1,qkvFormat:1}},Ia=(e,t,r)=>t&&e?`
      let total_sequence_length_input = u32(${t.getByOffset("0")});
      let present_sequence_length = max(total_sequence_length_input, uniforms.past_sequence_length);
      let is_subsequent_prompt: bool = sequence_length > 1 && sequence_length != total_sequence_length_input;
      let is_first_prompt: bool = is_subsequent_prompt == false && sequence_length == total_sequence_length_input;
      total_sequence_length = u32(${e?.getByOffset("batchIdx")}) + 1;
      var past_sequence_length: u32 = 0;
      if (is_first_prompt == false) {
        past_sequence_length = total_sequence_length - sequence_length;
      }
       `:`
    ${r?"let past_sequence_length = uniforms.past_sequence_length":""};
    let present_sequence_length = total_sequence_length;
    `,Ps=(e,t,r,i,a,n,s,o)=>{let u=A(s?1:n),l=64,d=n/u;d<l&&(l=32);let p=Math.ceil(n/u/l),h=[{type:12,data:t},{type:12,data:r},{type:12,data:i},{type:12,data:a},{type:12,data:d},{type:12,data:p}],f=O(e.dataType,u),m=C(1,u),w=["type"];s&&w.push("type"),o&&w.push("type");let $=_=>{let y=q("x",e.dataType,e.dims,u),S=[y],v=s?z("seq_lens",s.dataType,s.dims):void 0;v&&S.push(v);let E=o?z("total_sequence_length_input",o.dataType,o.dims):void 0;E&&S.push(E);let B=C(e.dataType),R=[{name:"batch_size",type:"u32"},{name:"num_heads",type:"u32"},{name:"past_sequence_length",type:"u32"},{name:"sequence_length",type:"u32"},{name:"total_sequence_length",type:"u32"},{name:"elements_per_thread",type:"u32"}];return`
  var<workgroup> thread_max: array<f32, ${l}>;
  var<workgroup> thread_sum: array<f32, ${l}>;
  ${_.registerUniforms(R).declareVariables(...S)}
  ${_.mainStart([l,1,1])}
    let batchIdx = workgroup_id.z / uniforms.num_heads;
    let headIdx = workgroup_id.z % uniforms.num_heads;
    let sequence_length = uniforms.sequence_length;
    var total_sequence_length = uniforms.total_sequence_length;
    ${Ia(v,E,!1)}
    let local_offset = local_idx * uniforms.elements_per_thread;
    let offset = (global_idx / ${l}) * uniforms.total_sequence_length + local_offset;
    let seq_causal_length = ${s?"u32(past_sequence_length + workgroup_id.y + 1)":"total_sequence_length"};
    var thread_max_vector = ${m}(-3.4028234663852886e+38f);
    for (var i: u32 = 0; i < uniforms.elements_per_thread && i + local_offset < seq_causal_length; i++) {
      thread_max_vector = max(${m}(x[offset + i]), thread_max_vector);
    }
    thread_max[local_idx] = ${(()=>{switch(u){case 1:return"thread_max_vector";case 2:return"max(thread_max_vector.x, thread_max_vector.y)";case 4:return"max(max(thread_max_vector.x, thread_max_vector.y), max(thread_max_vector.z, thread_max_vector.w))";default:throw new Error(`Unsupported components: ${u}`)}})()};
    workgroupBarrier();

    var max_value =  f32(-3.4028234663852886e+38f);
    for (var i = 0u; i < ${l}; i++) {
      max_value = max(thread_max[i], max_value);
    }

    var sum_vector = ${m}(0);
    for (var i: u32 = 0; i < uniforms.elements_per_thread && i + local_offset < seq_causal_length; i++) {
      sum_vector += exp(${m}(x[offset + i]) - max_value);
    }
    thread_sum[local_idx] = ${(()=>{switch(u){case 1:return"sum_vector";case 2:return"sum_vector.x + sum_vector.y";case 4:return"sum_vector.x + sum_vector.y + sum_vector.z + sum_vector.w";default:throw new Error(`Unsupported components: ${u}`)}})()};
    workgroupBarrier();

    var sum: f32 = 0;
    for (var i = 0u; i < ${l}; i++) {
      sum += thread_sum[i];
    }

    if (sum == 0) {
      for (var i: u32 = 0; i < uniforms.elements_per_thread && i + local_offset < seq_causal_length; i++) {
        x[offset + i] = ${y.type.value}(${B}(1.0) / ${B}(seq_causal_length));
      }
    } else {
      for (var i: u32 = 0; i < uniforms.elements_per_thread && i + local_offset < seq_causal_length; i++) {
        var f32input = ${m}(x[offset + i]);
        x[offset + i] = ${y.type.value}(exp(f32input - max_value) / sum);
      }
    }
      ${s?`
        for (var total_seq_id: u32 = seq_causal_length; total_seq_id + local_offset < uniforms.total_sequence_length; total_seq_id++) {
          x[offset + total_seq_id] = ${y.type.value}(${B}(0));
        }`:""};
  }`};return{name:"AttentionProbsSoftmax",shaderCache:{hint:`${l};${f};${u}`,inputDependencies:w},getShaderSource:$,getRunData:()=>({outputs:[],dispatchGroup:{x:1,y:a,z:t*r},programUniforms:h})}},Us=(e,t,r,i,a,n,s,o,u)=>{let l=s+n.kvSequenceLength,d=[n.batchSize,n.numHeads,n.sequenceLength,l],p=e>1&&i,h=n.kvNumHeads?n.kvNumHeads:n.numHeads,f=p?[n.batchSize,h,l,n.headSize]:void 0,m=n.nReps?n.nReps:1,w=n.scale===0?1/Math.sqrt(n.headSize):n.scale,$=A(n.headSize),_=n.headSize/$,y=12,S={x:Math.ceil(l/y),y:Math.ceil(n.sequenceLength/y),z:n.batchSize*n.numHeads},v=[{type:12,data:n.sequenceLength},{type:12,data:_},{type:12,data:l},{type:12,data:n.numHeads},{type:12,data:n.headSize},{type:1,data:w},{type:12,data:s},{type:12,data:n.kvSequenceLength},{type:12,data:m}],E=p&&i&&M.size(i.dims)>0,B=["type","type"];E&&B.push("type"),a&&B.push("type"),o&&B.push("type"),u&&B.push("type");let R=[{dims:d,dataType:t.dataType,gpuDataType:0}];p&&R.push({dims:f,dataType:t.dataType,gpuDataType:0});let U=W=>{let X=z("q",t.dataType,t.dims,$),ke=z("key",r.dataType,r.dims,$),ae=[X,ke];if(E){let fe=z("past_key",i.dataType,i.dims,$);ae.push(fe)}a&&ae.push(z("attention_bias",a.dataType,a.dims));let de=o?z("seq_lens",o.dataType,o.dims):void 0;de&&ae.push(de);let Me=u?z("total_sequence_length_input",u.dataType,u.dims):void 0;Me&&ae.push(Me);let j=q("output",t.dataType,d),re=[j];p&&re.push(q("present_key",t.dataType,f,$));let Ie=C(1,$),be=[{name:"M",type:"u32"},{name:"K",type:"u32"},{name:"N",type:"u32"},{name:"num_heads",type:"u32"},{name:"head_size",type:"u32"},{name:"alpha",type:"f32"},{name:"past_sequence_length",type:"u32"},{name:"kv_sequence_length",type:"u32"},{name:"n_reps",type:"u32"}];return`
  const TILE_SIZE = ${y}u;

  var<workgroup> tileQ: array<${X.type.storage}, ${y*y}>;
  var<workgroup> tileK: array<${X.type.storage}, ${y*y}>;
  ${W.registerUniforms(be).declareVariables(...ae,...re)}
  ${W.mainStart([y,y,1])}
    // x holds the N and y holds the M
    let headIdx = workgroup_id.z % uniforms.num_heads;
    let kvHeadIdx = ${m===1?"headIdx":"headIdx / uniforms.n_reps"};
    let kv_num_heads = ${m===1?"uniforms.num_heads":"uniforms.num_heads / uniforms.n_reps"};
    let batchIdx = workgroup_id.z / uniforms.num_heads;
    let m = workgroup_id.y * TILE_SIZE;
    let n = workgroup_id.x * TILE_SIZE;
    let sequence_length = uniforms.M;
    var total_sequence_length = uniforms.N;
    ${Ia(de,Me,!0)}
    let absKvHeadIdx = batchIdx * kv_num_heads + kvHeadIdx;
    let qOffset = workgroup_id.z * uniforms.M * uniforms.K + m * uniforms.K;
    ${E&&p?"let pastKeyOffset = absKvHeadIdx * uniforms.past_sequence_length * uniforms.K;":""};
    let kOffset = absKvHeadIdx * uniforms.kv_sequence_length * uniforms.K;
    ${p?"let presentKeyOffset = absKvHeadIdx * uniforms.N * uniforms.K;":""}
    var value = ${Ie}(0);
    for (var w: u32 = 0u; w < uniforms.K; w += TILE_SIZE) {
      if (global_id.y < uniforms.M && w + local_id.x < uniforms.K) {
        tileQ[TILE_SIZE * local_id.y + local_id.x] = q[qOffset + local_id.y * uniforms.K + w + local_id.x];
      }
      if (n + local_id.y < uniforms.N && w + local_id.x < uniforms.K) {
        var idx = TILE_SIZE * local_id.y + local_id.x;
      ${E&&p?`
              if (n + local_id.y < past_sequence_length) {
                tileK[idx] = past_key[pastKeyOffset + (n + local_id.y) * uniforms.K + w + local_id.x];
              } else if (n + local_id.y - past_sequence_length < uniforms.kv_sequence_length) {
                tileK[idx] = key[kOffset + (n + local_id.y - past_sequence_length) * uniforms.K + w + local_id.x];
              }`:`
          if (n + local_id.y < uniforms.kv_sequence_length) {
            tileK[idx] = key[kOffset + (n + local_id.y) * uniforms.K + w + local_id.x];
          }`}
      ${p?`if (n + local_id.y < present_sequence_length) {
        present_key[presentKeyOffset + (n + local_id.y) * uniforms.K + w + local_id.x] = tileK[idx];
      }`:""}
      }
      workgroupBarrier();

      for (var k: u32 = 0u; k < TILE_SIZE && w+k < uniforms.K; k++) {
          value += ${Ie}(tileQ[TILE_SIZE * local_id.y + k] * tileK[TILE_SIZE * local_id.x + k]);
      }

      workgroupBarrier();
    }

    if (global_id.y < uniforms.M && global_id.x < total_sequence_length) {
      let headOffset = workgroup_id.z * uniforms.M * uniforms.N;
      let outputIdx = headOffset + global_id.y * uniforms.N + global_id.x;
      var sum: f32 = ${(()=>{switch($){case 1:return"value";case 2:return"value.x + value.y";case 4:return"value.x + value.y + value.z + value.w";default:throw new Error(`Unsupported components: ${$}`)}})()};
        output[outputIdx] = ${j.type.value} (sum * uniforms.alpha) + ${a?"attention_bias[outputIdx]":"0.0"};
    }
  }`};return{name:"AttentionProbs",shaderCache:{hint:`${$};${a!==void 0};${i!==void 0};${e}`,inputDependencies:B},getRunData:()=>({outputs:R,dispatchGroup:S,programUniforms:v}),getShaderSource:U}},Ns=(e,t,r,i,a,n,s=void 0,o=void 0)=>{let u=n+a.kvSequenceLength,l=a.nReps?a.nReps:1,d=a.vHiddenSize*l,p=e>1&&i,h=a.kvNumHeads?a.kvNumHeads:a.numHeads,f=p?[a.batchSize,h,u,a.headSize]:void 0,m=[a.batchSize,a.sequenceLength,d],w=12,$={x:Math.ceil(a.vHeadSize/w),y:Math.ceil(a.sequenceLength/w),z:a.batchSize*a.numHeads},_=[{type:12,data:a.sequenceLength},{type:12,data:u},{type:12,data:a.vHeadSize},{type:12,data:a.numHeads},{type:12,data:a.headSize},{type:12,data:d},{type:12,data:n},{type:12,data:a.kvSequenceLength},{type:12,data:l}],y=p&&i&&M.size(i.dims)>0,S=["type","type"];y&&S.push("type"),s&&S.push("type"),o&&S.push("type");let v=[{dims:m,dataType:t.dataType,gpuDataType:0}];p&&v.push({dims:f,dataType:t.dataType,gpuDataType:0});let E=B=>{let R=z("probs",t.dataType,t.dims),U=z("v",r.dataType,r.dims),W=[R,U];y&&W.push(z("past_value",i.dataType,i.dims));let X=s?z("seq_lens",s.dataType,s.dims):void 0;s&&W.push(X);let ke=o?z("total_sequence_length_input",o.dataType,o.dims):void 0;o&&W.push(ke);let ae=[q("output",t.dataType,m)];p&&ae.push(q("present_value",t.dataType,f));let de=[{name:"M",type:"u32"},{name:"K",type:"u32"},{name:"N",type:"u32"},{name:"num_heads",type:"u32"},{name:"head_size",type:"u32"},{name:"v_hidden_size",type:"u32"},{name:"past_sequence_length",type:"u32"},{name:"kv_sequence_length",type:"u32"},{name:"n_reps",type:"u32"}];return`
  const TILE_SIZE = ${w}u;
  var<workgroup> tileQ: array<${R.type.value}, ${w*w}>;
  var<workgroup> tileV: array<${R.type.value}, ${w*w}>;
  ${B.registerUniforms(de).declareVariables(...W,...ae)}
  ${B.mainStart([w,w,1])}
   let headIdx = workgroup_id.z % uniforms.num_heads;
   let batchIdx = workgroup_id.z / uniforms.num_heads;
   let kvHeadIdx = ${l===1?"headIdx":"headIdx / uniforms.n_reps"};
   let kv_num_heads = ${l===1?"uniforms.num_heads":"uniforms.num_heads / uniforms.n_reps"};
   let m = global_id.y;
   let n = global_id.x;
   let sequence_length = uniforms.M;
   var total_sequence_length = uniforms.K;
   ${Ia(X,ke,!0)}
   let offsetA = workgroup_id.z * uniforms.M * uniforms.K + m * uniforms.K;
   let absKvHeadIdx = batchIdx * kv_num_heads + kvHeadIdx; // kvHeadIdx is relative to the batch
   ${y&&p?"let pastValueOffset = absKvHeadIdx * uniforms.N * uniforms.past_sequence_length + n;":""};
   let vOffset = absKvHeadIdx * uniforms.N * uniforms.kv_sequence_length + n;
   ${p?"let presentValueOffset = absKvHeadIdx * uniforms.N * uniforms.K + n;":""}
   var value = ${R.type.storage}(0);
   for (var w: u32 = 0u; w < uniforms.K; w += TILE_SIZE) {
      if (m < uniforms.M && w + local_id.x < uniforms.K) {
        tileQ[TILE_SIZE * local_id.y + local_id.x] = probs[offsetA + w + local_id.x];
      }
      if (n < uniforms.N && w + local_id.y < uniforms.K) {
        var idx = TILE_SIZE * local_id.y + local_id.x;
        ${y&&p?`
        if (w + local_id.y < past_sequence_length) {
          tileV[idx] = past_value[pastValueOffset + (w + local_id.y) * uniforms.N];
        } else if (w + local_id.y - past_sequence_length < uniforms.kv_sequence_length) {
          tileV[idx] = v[vOffset + (w + local_id.y - past_sequence_length) * uniforms.N];
        }
      `:`
            if (w + local_id.y < uniforms.kv_sequence_length) {
              tileV[idx] = v[vOffset + (w + local_id.y) * uniforms.N];
            }`}
        ${p?`
            if (w + local_id.y < present_sequence_length) {
          present_value[presentValueOffset + (w + local_id.y) * uniforms.N] = tileV[idx];
        }`:""}
      }
     workgroupBarrier();
     for (var k: u32 = 0u; k < TILE_SIZE && w+k < total_sequence_length; k++) {
       value += tileQ[TILE_SIZE * local_id.y + k] * tileV[TILE_SIZE * k + local_id.x];
     }
     workgroupBarrier();
   }

   // we need to transpose output from BNSH_v to BSND_v
   if (m < uniforms.M && n < uniforms.N) {
     let outputIdx = batchIdx * uniforms.M * uniforms.v_hidden_size + m * uniforms.v_hidden_size
       + headIdx * uniforms.N + n;
     output[outputIdx] = value;
   }
  }`};return{name:"AttentionScore",shaderCache:{hint:`${i!==void 0};${e}`,inputDependencies:S},getRunData:()=>({outputs:v,dispatchGroup:$,programUniforms:_}),getShaderSource:E}},Ji=(e,t,r,i,a,n,s,o,u,l,d=void 0,p=void 0)=>{let h=Math.min(e.outputCount,1+(s?1:0)+(o?1:0)),f=h>1?l.pastSequenceLength:0,m=f+l.kvSequenceLength,w=u&&M.size(u.dims)>0?u:void 0,$=[t,r];h>1&&s&&M.size(s.dims)>0&&$.push(s),w&&$.push(w),d&&$.push(d),p&&$.push(p);let _=e.compute(Us(h,t,r,s,w,l,f,d,p),{inputs:$,outputs:h>1?[-1,1]:[-1]})[0];e.compute(Ps(_,l.batchSize,l.numHeads,f,l.sequenceLength,m,d,p),{inputs:d&&p?[_,d,p]:[_],outputs:[]});let y=[_,i];h>1&&o&&M.size(o.dims)>0&&y.push(o),d&&y.push(d),p&&y.push(p),e.compute(Ns(h,_,i,o,l,f,d,p),{inputs:y,outputs:h>1?[0,2]:[0]})},Ls=(e,t)=>{let r=[t.batchSize,t.numHeads,t.sequenceLength,t.headSize],i=t.sequenceLength,a=t.inputHiddenSize,n=t.headSize,s=12,o={x:Math.ceil(t.headSize/s),y:Math.ceil(t.sequenceLength/s),z:t.batchSize*t.numHeads},u=[e.inputs[0],e.inputs[1],e.inputs[2]],l=[{type:12,data:i},{type:12,data:a},{type:12,data:n},{type:12,data:t.numHeads},{type:12,data:t.headSize},{type:12,data:t.hiddenSize},{type:12,data:t.hiddenSize+t.hiddenSize+t.vHiddenSize}],d=p=>{let h=q("output_q",u[0].dataType,r),f=q("output_k",u[0].dataType,r),m=q("output_v",u[0].dataType,r),w=z("input",u[0].dataType,u[0].dims),$=z("weight",u[1].dataType,u[1].dims),_=z("bias",u[2].dataType,u[2].dims),y=w.type.storage,S=[{name:"M",type:"u32"},{name:"K",type:"u32"},{name:"N",type:"u32"},{name:"num_heads",type:"u32"},{name:"head_size",type:"u32"},{name:"hidden_size",type:"u32"},{name:"ldb",type:"u32"}];return`
  const TILE_SIZE = ${s}u;
  var<workgroup> tileInput: array<${y}, ${s*s}>;
  var<workgroup> tileWeightQ: array<${y}, ${s*s}>;
  var<workgroup> tileWeightK: array<${y}, ${s*s}>;
  var<workgroup> tileWeightV: array<${y}, ${s*s}>;
  ${p.registerUniforms(S).declareVariables(w,$,_,h,f,m)}
  ${p.mainStart([s,s,1])}
    let batchIndex = workgroup_id.z / uniforms.num_heads;
    let headNumber = workgroup_id.z % uniforms.num_heads;
    let m = global_id.y;
    let n = global_id.x;

    let inputOffset = batchIndex * (uniforms.M * uniforms.K) + m * uniforms.K;
    let biasOffsetQ = headNumber * uniforms.head_size;
    let biasOffsetK = uniforms.hidden_size + biasOffsetQ;
    let biasOffsetV = uniforms.hidden_size + biasOffsetK;

    var valueQ = ${y}(0);
    var valueK = ${y}(0);
    var valueV = ${y}(0);
    for (var w: u32 = 0u; w < uniforms.K; w += TILE_SIZE) {
      if (m < uniforms.M && w + local_id.x < uniforms.K) {
        tileInput[TILE_SIZE * local_id.y + local_id.x] = input[inputOffset + w + local_id.x];
      }
      if (n < uniforms.N && w + local_id.y < uniforms.K) {
        let offset = n + (w + local_id.y) * uniforms.ldb;
        tileWeightQ[TILE_SIZE * local_id.y + local_id.x] = weight[biasOffsetQ + offset];
        tileWeightK[TILE_SIZE * local_id.y + local_id.x] = weight[biasOffsetK + offset];
        tileWeightV[TILE_SIZE * local_id.y + local_id.x] = weight[biasOffsetV + offset];
      }
      workgroupBarrier();
      for (var k: u32 = 0u; k<TILE_SIZE && w+k < uniforms.K; k++) {
        let inputTileOffset = TILE_SIZE * local_id.y + k;
        let weightTileOffset = TILE_SIZE * k + local_id.x;
        valueQ += tileInput[inputTileOffset] * tileWeightQ[weightTileOffset];
        valueK += tileInput[inputTileOffset] * tileWeightK[weightTileOffset];
        valueV += tileInput[inputTileOffset] * tileWeightV[weightTileOffset];
      }

      workgroupBarrier();
    }

    let headOffset = (m * uniforms.N + n) % uniforms.head_size;
    valueQ += bias[headOffset + biasOffsetQ];
    valueK += bias[headOffset + biasOffsetK];
    valueV += bias[headOffset + biasOffsetV];

    let offset = workgroup_id.z * uniforms.M * uniforms.N;
    if (m < uniforms.M && n < uniforms.N) {
      let outputIdx = offset + m * uniforms.N + n;
      output_q[outputIdx] = valueQ;
      output_k[outputIdx] = valueK;
      output_v[outputIdx] = valueV;
    }
  }`};return e.compute({name:"AttentionPrepare",shaderCache:{inputDependencies:["type","type","type"]},getRunData:()=>({outputs:[{dims:r,dataType:e.inputs[0].dataType,gpuDataType:0},{dims:r,dataType:e.inputs[0].dataType,gpuDataType:0},{dims:r,dataType:e.inputs[0].dataType,gpuDataType:0}],dispatchGroup:o,programUniforms:l}),getShaderSource:d},{inputs:u,outputs:[-1,-1,-1]})},Vs=(e,t)=>{let r=Ds(e.inputs,t),[i,a,n]=Ls(e,r);return Ji(e,i,a,n,e.inputs[4],void 0,void 0,void 0,e.inputs[5],r)}}),qs,Fs,Ws,Gs,mc=I(()=>{Ye(),ue(),oe(),b(),Z(),qs=(e,t)=>{if(!e||e.length!==5)throw new Error("BatchNormalization requires 5 inputs");let r=(i,a,n)=>{let s=a.length;if(s!==i.length)throw new Error(`${n}: num dimensions != ${s}`);a.forEach((o,u)=>{if(o!==i[u])throw new Error(`${n}: dim[${u}] do not match`)})};if(e[0].dims.length>1){let i=t.format==="NHWC"?t.spatial?e[0].dims.slice(-1):e[0].dims.slice(-1).concat(e[0].dims.slice(1,e[0].dims.length-1)):e[0].dims.slice(1,t.spatial?2:void 0);r(e[1].dims,i,"Invalid input scale"),r(e[2].dims,i,"Invalid input B"),r(e[3].dims,i,"Invalid input mean"),r(e[4].dims,i,"Invalid input var")}else r(e[1].dims,[1],"Invalid input scale"),r(e[2].dims,[1],"Invalid input B"),r(e[3].dims,[1],"Invalid input mean"),r(e[4].dims,[1],"Invalid input var")},Fs=(e,t)=>{let{epsilon:r,spatial:i,format:a}=t,n=e[0].dims,s=i?A(n[n.length-1]):1,o=a==="NHWC"&&n.length>1?s:1,u=M.size(n)/s,l=i,d=l?n.length:n,p=z("x",e[0].dataType,e[0].dims,s),h=z("scale",e[1].dataType,e[1].dims,o),f=z("bias",e[2].dataType,e[2].dims,o),m=z("inputMean",e[3].dataType,e[3].dims,o),w=z("inputVar",e[4].dataType,e[4].dims,o),$=q("y",e[0].dataType,d,s),_=()=>{let S="";if(i)S=`let cOffset = ${n.length===1?"0u":a==="NHWC"?`outputIndices[${n.length-1}] / ${s}`:"outputIndices[1]"};`;else if(a==="NCHW")S=`
            ${$.indicesSet("outputIndices","0","0")}
            let cOffset = ${$.indicesToOffset("outputIndices")};`;else{S=`var cIndices = ${h.type.indices}(0);
                       cIndices[0] = outputIndices[${n.length-1}];`;for(let v=1;v<h.rank;v++)S+=`cIndices[${v}] = outputIndices[${v}];`;S+=`let cOffset = ${h.indicesToOffset("cIndices")};`}return S},y=S=>`
  const epsilon = ${r};
  ${S.registerUniform("outputSize","u32").declareVariables(p,h,f,m,w,$)}
  ${S.mainStart()}
  ${S.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}
    var outputIndices = ${$.offsetToIndices(`global_idx * ${s}`)};
    ${_()}
    let scale = ${h.getByOffset("cOffset")};
    let bias = ${f.getByOffset("cOffset")};
    let inputMean = ${m.getByOffset("cOffset")};
    let inputVar = ${w.getByOffset("cOffset")};
    let x = ${p.getByOffset("global_idx")};
    let value = (x - inputMean) * inverseSqrt(inputVar + epsilon) * scale + bias;
    ${$.setByOffset("global_idx","value")}
  }`;return{name:"BatchNormalization",shaderCache:{hint:`${t.epsilon}_${t.format}_${i}_${s}`,inputDependencies:l?["rank","type","type","type","type"]:void 0},getShaderSource:y,getRunData:()=>({outputs:[{dims:e[0].dims,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(u/64)},programUniforms:l?[{type:12,data:u},...k(n)]:[{type:12,data:u}]})}},Ws=e=>g(e),Gs=(e,t)=>{let{inputs:r,outputCount:i}=e,a=Ws({...t,outputCount:i});if(ie.webgpu.validateInputContent&&qs(r,a),t.trainingMode)throw new Error("BatchNormalization trainingMode is not supported yet.");e.compute(Fs(r,a))}}),js,Hs,Ks,gc=I(()=>{oe(),Z(),js=e=>{if(e[0].dims.length!==3)throw new Error("input should have 3 dimensions");if(![320,640,1280].includes(e[0].dims[2]))throw new Error("number of channels should be 320, 640 or 1280");if(e[1].dims.length!==1)throw new Error("bias is expected to have 1 dimensions");if(e[0].dims[2]!==e[1].dims[0])throw new Error("last dimension of input and bias are not the same")},Hs=e=>{let t=e[0].dims,r=e[0].dims[2],i=M.size(t)/4,a=e[0].dataType,n=z("input",a,t,4),s=z("bias",a,[r],4),o=z("residual",a,t,4),u=q("output",a,t,4);return{name:"BiasAdd",getRunData:()=>({outputs:[{dims:t,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(i/64)}}),getShaderSource:l=>`
  const channels = ${r}u / 4;
  ${l.declareVariables(n,s,o,u)}

  ${l.mainStart()}
    ${l.guardAgainstOutOfBoundsWorkgroupSizes(i)}
    let value = ${n.getByOffset("global_idx")}
      + ${s.getByOffset("global_idx % channels")} + ${o.getByOffset("global_idx")};
    ${u.setByOffset("global_idx","value")}
  }`}},Ks=e=>{js(e.inputs),e.compute(Hs(e.inputs))}}),Zs,Be,Qs,Xs,Ys,Js,eo,to,ro,io,ao,no,so,oo,uo,lo,ea,po,Ca,co,ho,fo,mo,go,yo,wo,_o,bo,$o,vo,xo,So,To,Eo,ko,sn,Io,on,un,Co,zo,Ao,Oo,Ro,Bo,ln=I(()=>{ue(),oe(),b(),Z(),Zs=(e,t,r,i,a,n,s)=>{let o=Math.ceil(t/4),u="";typeof a=="string"?u=`${a}(a)`:u=a("a");let l=z("inputData",r,[o],4),d=q("outputData",i,[o],4),p=[{name:"vec_size",type:"u32"}];return s&&p.push(...s),`
      ${e.registerUniforms(p).declareVariables(l,d)}

  ${n??""}

  ${e.mainStart()}
    ${e.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.vec_size")}

    let a = ${l.getByOffset("global_idx")};
    ${d.setByOffset("global_idx",u)}
  }`},Be=(e,t,r,i,a,n=e.dataType,s,o)=>{let u=[{type:12,data:Math.ceil(M.size(e.dims)/4)}];return s&&u.push(...s),{name:t,shaderCache:{hint:a,inputDependencies:["type"]},getShaderSource:l=>Zs(l,M.size(e.dims),e.dataType,n,r,i,o),getRunData:l=>({outputs:[{dims:e.dims,dataType:n}],dispatchGroup:{x:Math.ceil(M.size(l[0].dims)/64/4)},programUniforms:u})}},Qs=e=>{e.compute(Be(e.inputs[0],"Abs","abs"))},Xs=e=>{e.compute(Be(e.inputs[0],"Acos","acos"))},Ys=e=>{e.compute(Be(e.inputs[0],"Acosh","acosh"))},Js=e=>{e.compute(Be(e.inputs[0],"Asin","asin"))},eo=e=>{e.compute(Be(e.inputs[0],"Asinh","asinh"))},to=e=>{e.compute(Be(e.inputs[0],"Atan","atan"))},ro=e=>{e.compute(Be(e.inputs[0],"Atanh","atanh"))},io=e=>g(e),ao=(e,t)=>{let r;switch(t.to){case 10:r="vec4<f16>";break;case 1:r="vec4<f32>";break;case 12:r="vec4<u32>";break;case 6:r="vec4<i32>";break;case 9:r="vec4<bool>";break;default:throw new RangeError(`not supported type (specified in attribute 'to' from 'Cast' operator): ${t.to}`)}e.compute(Be(e.inputs[0],"Cast",r,void 0,t.cacheKey,t.to))},no=e=>{let t,r,i=e.length>=2&&e[1].data!==0,a=e.length>=3&&e[2].data!==0;switch(e[0].dataType){case 1:t=i?e[1].getFloat32Array()[0]:-34028234663852886e22,r=a?e[2].getFloat32Array()[0]:34028234663852886e22;break;case 10:t=i?e[1].getUint16Array()[0]:64511,r=a?e[2].getUint16Array()[0]:31743;break;default:throw new Error("Unsupport data type")}return g({min:t,max:r})},so=(e,t)=>{let r=t||no(e.inputs),i=C(e.inputs[0].dataType);e.compute(Be(e.inputs[0],"Clip",a=>`clamp(${a}, vec4<${i}>(uniforms.min), vec4<${i}>(uniforms.max))`,void 0,r.cacheKey,void 0,[{type:e.inputs[0].dataType,data:r.min},{type:e.inputs[0].dataType,data:r.max}],[{name:"min",type:i},{name:"max",type:i}]),{inputs:[0]})},oo=e=>{e.compute(Be(e.inputs[0],"Ceil","ceil"))},uo=e=>{e.compute(Be(e.inputs[0],"Cos","cos"))},lo=e=>{e.compute(Be(e.inputs[0],"Cosh","cosh"))},ea=e=>g(e),po=(e,t)=>{let r=C(e.inputs[0].dataType);e.compute(Be(e.inputs[0],"Elu",i=>`elu_vf32(${i})`,`
  const elu_alpha_ = ${r}(${t.alpha});

  fn elu_f32(a: ${r}) -> ${r} {
  return select((exp(a) - 1.0) * elu_alpha_, a, a >= 0.0);
  }

  fn elu_vf32(v: vec4<${r}>) -> vec4<${r}> {
  return vec4(elu_f32(v.x), elu_f32(v.y), elu_f32(v.z), elu_f32(v.w));
  }`,t.cacheKey))},Ca=(e="f32")=>`
const r0: ${e} = 0.3275911;
const r1: ${e} = 0.254829592;
const r2: ${e} = -0.284496736;
const r3: ${e} = 1.421413741;
const r4: ${e} = -1.453152027;
const r5: ${e} = 1.061405429;

fn erf_vf32(v: vec4<${e}>) -> vec4<${e}> {
  let absv = abs(v);
  let x = 1.0 / (1.0 + r0 * absv);
  return sign(v) * (1.0 - ((((r5 * x + r4) * x + r3) * x + r2) * x + r1) * x * exp(-absv * absv));
}`,co=e=>{let t=C(e.inputs[0].dataType);e.compute(Be(e.inputs[0],"Erf",r=>`erf_vf32(${r})`,Ca(t)))},ho=e=>{e.compute(Be(e.inputs[0],"Exp","exp"))},fo=e=>{e.compute(Be(e.inputs[0],"Floor","floor"))},mo=e=>{let t=C(e.inputs[0].dataType);e.compute(Be(e.inputs[0],"Gelu",r=>`0.5 * ${r} * (1.0 + erf_vf32(${r} * 0.7071067811865475))`,Ca(t)))},go=(e,t)=>{let r=C(e.inputs[0].dataType);e.compute(Be(e.inputs[0],"LeakyRelu",i=>`select(leaky_relu_alpha_ * ${i}, ${i}, ${i} >= vec4<${r}>(0.0))`,`const leaky_relu_alpha_ = ${r}(${t.alpha});`,t.cacheKey))},yo=e=>{e.compute(Be(e.inputs[0],"Not",t=>`!${t}`))},wo=e=>{e.compute(Be(e.inputs[0],"Neg",t=>`-${t}`))},_o=e=>{e.compute(Be(e.inputs[0],"Reciprocal",t=>`1.0/${t}`))},bo=e=>{let t=C(e.inputs[0].dataType);e.compute(Be(e.inputs[0],"Relu",r=>`select(vec4<${t}>(0.0), ${r}, ${r} > vec4<${t}>(0.0))`))},$o=e=>{e.compute(Be(e.inputs[0],"Sigmoid",t=>`(1.0 / (1.0 + exp(-${t})))`))},vo=e=>g(e),xo=(e,t)=>{let r=C(e.inputs[0].dataType);e.compute(Be(e.inputs[0],"HardSigmoid",i=>`max(vec4<${r}>(0.0), min(vec4<${r}>(1.0), ${t.alpha} * ${i} + vec4<${r}>(${t.beta})))`,void 0,t.cacheKey))},So=e=>{e.compute(Be(e.inputs[0],"Sin","sin"))},To=e=>{e.compute(Be(e.inputs[0],"Sinh","sinh"))},Eo=e=>{e.compute(Be(e.inputs[0],"Sqrt","sqrt"))},ko=e=>{e.compute(Be(e.inputs[0],"Tan","tan"))},sn=e=>`sign(${e}) * (1 - exp(-2 * abs(${e}))) / (1 + exp(-2 * abs(${e})))`,Io=e=>{e.compute(Be(e.inputs[0],"Tanh",sn))},on=(e="f32")=>`
const fast_gelu_a: ${e} = 0.5;
const fast_gelu_b: ${e} = 0.7978845608028654;
const fast_gelu_c: ${e} = 0.035677408136300125;

fn tanh_v(v: vec4<${e}>) -> vec4<${e}> {
  return ${sn("v")};
}
`,un=e=>`(fast_gelu_a + fast_gelu_a * tanh_v(${e} * (fast_gelu_c * ${e} * ${e} + fast_gelu_b))) * ${e}`,Co=e=>{let t=C(e.inputs[0].dataType);e.compute(Be(e.inputs[0],"FastGelu",un,on(t),void 0,e.inputs[0].dataType))},zo=(e,t)=>{let r=C(e.inputs[0].dataType);return e.compute(Be(e.inputs[0],"ThresholdedRelu",i=>`select(vec4<${r}>(0.0), ${i}, ${i} > thresholded_relu_alpha_)`,`const thresholded_relu_alpha_ = vec4<${r}>(${t.alpha});`,t.cacheKey)),0},Ao=e=>{e.compute(Be(e.inputs[0],"Log","log"))},Oo=(e,t)=>`
const alpha = vec4<${e}>(${t});
const one = ${e}(1.0);
const zero = ${e}(0.0);

fn quick_gelu_impl(x: vec4<${e}>) -> vec4<${e}> {
  let v = x *alpha;
  var x1 : vec4<${e}>;
  for (var i = 0; i < 4; i = i + 1) {
    if (v[i] >= zero) {
      x1[i] = one / (one + exp(-v[i]));
    } else {
      x1[i] = one - one / (one + exp(v[i]));
    }
  }
  return x * x1;
}
`,Ro=e=>`quick_gelu_impl(${e})`,Bo=(e,t)=>{let r=C(e.inputs[0].dataType);e.compute(Be(e.inputs[0],"QuickGelu",Ro,Oo(r,t.alpha),t.cacheKey,e.inputs[0].dataType))}}),Mo,Do,Po,yc=I(()=>{oe(),Z(),ln(),Mo=e=>{if(e[0].dims.length!==3)throw new Error("input should have 3 dimensions");if(![2560,5120,10240].includes(e[0].dims[2]))throw new Error("hidden state should be 2560, 5120 or 10240");if(e[1].dims.length!==1)throw new Error("bias is expected to have 1 dimensions");if(e[0].dims[2]!==e[1].dims[0])throw new Error("last dimension of input and bias are not the same")},Do=e=>{let t=e[0].dims.slice();t[2]=t[2]/2;let r=z("input",e[0].dataType,e[0].dims,4),i=z("bias",e[0].dataType,[e[0].dims[2]],4),a=q("output",e[0].dataType,t,4),n=M.size(t)/4,s=O(e[0].dataType);return{name:"BiasSplitGelu",getRunData:()=>({outputs:[{dims:t,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(n/64)}}),getShaderSource:o=>`
  const M_SQRT2 = sqrt(2.0);
  const halfChannels = ${e[0].dims[2]/4/2}u;

  ${o.declareVariables(r,i,a)}

  ${Ca(s)}

  ${o.mainStart()}
    ${o.guardAgainstOutOfBoundsWorkgroupSizes(n)}
    let biasIdx = global_idx % halfChannels;
    let batchIndex = global_idx / halfChannels;
    let inputOffset = biasIdx + batchIndex * halfChannels * 2;
    let valueLeft = input[inputOffset] + bias[biasIdx];
    let valueRight = input[inputOffset + halfChannels] + bias[biasIdx + halfChannels];
    let geluRight = valueRight * 0.5 * (erf_vf32(valueRight / M_SQRT2) + 1);

    ${a.setByOffset("global_idx","valueLeft * geluRight")}
  }`}},Po=e=>{Mo(e.inputs),e.compute(Do(e.inputs))}}),Uo,No,Mt,Lo,Vo,qo,Fo,Wo,Go,jo,Ho,Ko,Zo,wc=I(()=>{ue(),oe(),Z(),Uo=(e,t,r,i,a,n,s,o,u,l,d,p)=>{let h,f;typeof o=="string"?h=f=(y,S)=>`${o}((${y}),(${S}))`:typeof o=="function"?h=f=o:(h=o.scalar,f=o.vector);let m=q("outputData",d,i.length,4),w=z("aData",u,t.length,4),$=z("bData",l,r.length,4),_;if(a)if(n){let y=M.size(t)===1,S=M.size(r)===1,v=t.length>0&&t[t.length-1]%4===0,E=r.length>0&&r[r.length-1]%4===0;y||S?_=m.setByOffset("global_idx",f(y?`${w.type.value}(${w.getByOffset("0")}.x)`:w.getByOffset("global_idx"),S?`${$.type.value}(${$.getByOffset("0")}.x)`:$.getByOffset("global_idx"))):_=`
            let outputIndices = ${m.offsetToIndices("global_idx * 4u")};
            let offsetA = ${w.broadcastedIndicesToOffset("outputIndices",m)};
            let offsetB = ${$.broadcastedIndicesToOffset("outputIndices",m)};
            ${m.setByOffset("global_idx",f(s||v?w.getByOffset("offsetA / 4u"):`${w.type.value}(${w.getByOffset("offsetA / 4u")}[offsetA % 4u])`,s||E?$.getByOffset("offsetB / 4u"):`${$.type.value}(${$.getByOffset("offsetB / 4u")}[offsetB % 4u])`))}
          `}else _=m.setByOffset("global_idx",f(w.getByOffset("global_idx"),$.getByOffset("global_idx")));else{if(!n)throw new Error("no necessary to use scalar implementation for element-wise binary op implementation.");let y=(S,v,E="")=>{let B=`aData[indexA${v}][componentA${v}]`,R=`bData[indexB${v}][componentB${v}]`;return`
            let outputIndices${v} = ${m.offsetToIndices(`global_idx * 4u + ${v}u`)};
            let offsetA${v} = ${w.broadcastedIndicesToOffset(`outputIndices${v}`,m)};
            let offsetB${v} = ${$.broadcastedIndicesToOffset(`outputIndices${v}`,m)};
            let indexA${v} = offsetA${v} / 4u;
            let indexB${v} = offsetB${v} / 4u;
            let componentA${v} = offsetA${v} % 4u;
            let componentB${v} = offsetB${v} % 4u;
            ${S}[${v}] = ${E}(${h(B,R)});
          `};d===9?_=`
            var data = vec4<u32>(0);
            ${y("data",0,"u32")}
            ${y("data",1,"u32")}
            ${y("data",2,"u32")}
            ${y("data",3,"u32")}
            outputData[global_idx] = dot(vec4<u32>(0x1, 0x100, 0x10000, 0x1000000), vec4<u32>(data));`:_=`
            ${y("outputData[global_idx]",0)}
            ${y("outputData[global_idx]",1)}
            ${y("outputData[global_idx]",2)}
            ${y("outputData[global_idx]",3)}
          `}return`
        ${e.registerUniform("vec_size","u32").declareVariables(w,$,m)}

        ${p??""}

        ${e.mainStart()}
        ${e.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.vec_size")}
        ${_}
      }`},No=(e,t,r,i,a,n,s=r.dataType)=>{let o=r.dims.map(Number),u=i.dims.map(Number),l=!M.areEqual(o,u),d=o,p=M.size(o),h=!1,f=!1,m=[l];if(l){let w=Lt.calcShape(o,u,!1);if(!w)throw new Error("Can't perform binary op on the given tensors");d=w.slice(),p=M.size(d);let $=M.size(o)===1,_=M.size(u)===1,y=o.length>0&&o[o.length-1]%4===0,S=u.length>0&&u[u.length-1]%4===0;m.push($),m.push(_),m.push(y),m.push(S);let v=1;for(let E=1;E<d.length;E++){let B=o[o.length-E],R=u[u.length-E];if(B===R)v*=B;else break}v%4===0?(f=!0,h=!0):($||_||y||S)&&(h=!0)}else h=!0;return m.push(h),{name:e,shaderCache:{hint:t+m.map(w=>w.toString()).join("_"),inputDependencies:["rank","rank"]},getShaderSource:w=>Uo(w,o,u,d,h,l,f,a,r.dataType,i.dataType,s,n),getRunData:()=>({outputs:[{dims:d,dataType:s}],dispatchGroup:{x:Math.ceil(p/64/4)},programUniforms:[{type:12,data:Math.ceil(M.size(d)/4)},...k(o,u,d)]})}},Mt=(e,t,r,i,a,n)=>{e.compute(No(t,a??"",e.inputs[0],e.inputs[1],r,i,n))},Lo=e=>{Mt(e,"Add",(t,r)=>`${t}+${r}`)},Vo=e=>{Mt(e,"Div",(t,r)=>`${t}/${r}`)},qo=e=>{Mt(e,"Equal",{scalar:(t,r)=>`u32(${t}==${r})`,vector:(t,r)=>`vec4<u32>(${t}==${r})`},void 0,void 0,9)},Fo=e=>{Mt(e,"Mul",(t,r)=>`${t}*${r}`)},Wo=e=>{let t=z("input",e.inputs[0].dataType,e.inputs[0].dims).type.value;Mt(e,"Pow",{scalar:(r,i)=>`pow_custom(${r},${i})`,vector:(r,i)=>`pow_vector_custom(${r},${i})`},`
    fn pow_custom(a : ${t}, b : ${t}) -> ${t} {
      if (b == ${t}(0.0)) {
        return ${t}(1.0);
      } else if (a < ${t}(0.0) && f32(b) != floor(f32(b))) {
        return ${t}(pow(f32(a), f32(b))); // NaN
      }
      return select(sign(a), ${t}(1.0), round(f32(abs(b) % ${t}(2.0))) != 1.0) * ${t}(${t==="i32"?"round":""}(pow(f32(abs(a)), f32(b))));
    }
    fn pow_vector_custom(a : vec4<${t}>, b : vec4<${t}>) -> vec4<${t}> {
      // TODO: implement vectorized pow
      return vec4<${t}>(pow_custom(a.x, b.x), pow_custom(a.y, b.y), pow_custom(a.z, b.z), pow_custom(a.w, b.w));
    }
      `)},Go=e=>{Mt(e,"Sub",(t,r)=>`${t}-${r}`)},jo=e=>{Mt(e,"Greater",{scalar:(t,r)=>`u32(${t}>${r})`,vector:(t,r)=>`vec4<u32>(${t}>${r})`},void 0,void 0,9)},Ho=e=>{Mt(e,"Less",{scalar:(t,r)=>`u32(${t}<${r})`,vector:(t,r)=>`vec4<u32>(${t}<${r})`},void 0,void 0,9)},Ko=e=>{Mt(e,"GreaterOrEqual",{scalar:(t,r)=>`u32(${t}>=${r})`,vector:(t,r)=>`vec4<u32>(${t}>=${r})`},void 0,void 0,9)},Zo=e=>{Mt(e,"LessOrEqual",{scalar:(t,r)=>`u32(${t}<=${r})`,vector:(t,r)=>`vec4<u32>(${t}<=${r})`},void 0,void 0,9)}}),Qo,Xo,Yo,Jo,eu,tu,_c=I(()=>{ue(),oe(),b(),Z(),Qo=(e,t)=>{if(!e||e.length<1)throw new Error("too few inputs");let r=0,i=e[r],a=i.dataType,n=i.dims.length;e.forEach((s,o)=>{if(o!==r){if(s.dataType!==a)throw new Error("input tensors should be one type");if(s.dims.length!==n)throw new Error("input tensors should have the same shape");s.dims.forEach((u,l)=>{if(l!==t&&u!==i.dims[l])throw new Error("non concat dimensions must match")})}})},Xo=(e,t)=>`
  fn calculateInputIndex(index: u32) -> u32 {
    let sizeInConcatAxis = array<u32, ${e}u>(${t});
    for (var i: u32 = 0u; i < ${e}; i += 1u ) {
      if (index < sizeInConcatAxis[i]) {
        return i;
      }
    }
    return ${e}u;
  }`,Yo=(e,t)=>{let r=e.length,i=[];for(let a=0;a<r;++a){let n=t.setByOffset("global_idx",e[a].getByIndices("indices"));r===1?i.push(n):a===0?i.push(`if (inputIndex == ${a}u) { ${n} }`):a===r-1?i.push(`else { ${n} }`):i.push(`else if (inputIndex == ${a}) { ${n} }`)}return i.join(`
`)},Jo=(e,t,r,i)=>{let a=M.size(r),n=new Array(e.length),s=new Array(e.length),o=0,u=[],l=[],d=[{type:12,data:a}];for(let w=0;w<e.length;++w)o+=e[w].dims[t],n[w]=o,l.push(e[w].dims.length),s[w]=z(`input${w}`,i,l[w]),u.push("rank"),d.push({type:12,data:n[w]});for(let w=0;w<e.length;++w)d.push(...k(e[w].dims));d.push(...k(r));let p=q("output",i,r.length),h=p.indicesGet("indices",t),f=Array.from(Array(n.length).keys()).map(w=>`uniforms.sizeInConcatAxis${w}`).join(","),m=w=>`

  ${(()=>{w.registerUniform("outputSize","u32");for(let $=0;$<e.length;$++)w.registerUniform(`sizeInConcatAxis${$}`,"u32");return w.declareVariables(...s,p)})()}

  ${Xo(n.length,f)}

  ${w.mainStart()}
    ${w.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}

    var indices = ${p.offsetToIndices("global_idx")};

    let inputIndex = calculateInputIndex(${h});
    if (inputIndex != 0u) {
      let sizeInConcatAxis = array<u32, ${n.length}u>(${f});
      ${h} -= sizeInConcatAxis[inputIndex - 1u];
    }

    ${Yo(s,p)}
  }`;return{name:"Concat",shaderCache:{hint:`${t}`,inputDependencies:u},getRunData:()=>({outputs:[{dims:r,dataType:i}],dispatchGroup:{x:Math.ceil(a/64)},programUniforms:d}),getShaderSource:m}},eu=(e,t)=>{let r=e.inputs,i=r[0].dims,a=M.normalizeAxis(t.axis,i.length);Qo(r,a);let n=i.slice();n[a]=r.reduce((o,u)=>o+(u.dims.length>a?u.dims[a]:0),0);let s=r.filter(o=>M.size(o.dims)>0);e.compute(Jo(s,a,n,r[0].dataType),{inputs:s})},tu=e=>g({axis:e.axis})}),Lr,Vr,qr,dn,Fr=I(()=>{ue(),oe(),Lr=(e,t,r="f32")=>{switch(e.activation){case"Relu":return`value = max(value, ${t}(0.0));`;case"Sigmoid":return`value = (${t}(1.0) / (${t}(1.0) + exp(-value)));`;case"Clip":return`value = clamp(value, ${t}(${r}(uniforms.clip_min)), ${t}(${r}(uniforms.clip_max)));`;case"HardSigmoid":return`value = max(${t}(0.0), min(${t}(1.0), ${r}(uniforms.alpha) * value + ${r}(uniforms.beta)));`;case"LeakyRelu":return`value = select(${r}(uniforms.alpha) * value, value, value >= ${t}(0.0));`;case"Tanh":return`let e2x = exp(-2.0 * abs(value));
              value = sign(value) * (1.0 - e2x) / (1.0 + e2x);
        `;case"":return"";default:throw new Error(`Unsupported activation ${e.activation}`)}},Vr=(e,t)=>{e.activation==="Clip"?t.push({type:1,data:e.clipMax},{type:1,data:e.clipMin}):e.activation==="HardSigmoid"?t.push({type:1,data:e.alpha},{type:1,data:e.beta}):e.activation==="LeakyRelu"&&t.push({type:1,data:e.alpha})},qr=(e,t)=>{e.activation==="Clip"?t.push({name:"clip_max",type:"f32"},{name:"clip_min",type:"f32"}):e.activation==="HardSigmoid"?t.push({name:"alpha",type:"f32"},{name:"beta",type:"f32"}):e.activation==="LeakyRelu"&&t.push({name:"alpha",type:"f32"})},dn=e=>{let t=e?.activation||"";if(t==="HardSigmoid"){let[r,i]=e?.activation_params||[.2,.5];return{activation:t,alpha:r,beta:i}}else if(t==="Clip"){let[r,i]=e?.activation_params||[qi,It];return{activation:t,clipMax:i,clipMin:r}}else if(t==="LeakyRelu"){let[r]=e?.activation_params||[.01];return{activation:t,alpha:r}}return{activation:t}}}),at,ru,pn=I(()=>{at=(e,t)=>{switch(e){case 1:return t;case 2:return`vec2<${t}>`;case 3:return`vec3<${t}>`;case 4:return`vec4<${t}>`;default:throw new Error(`${e}-component is not supported.`)}},ru=e=>`
      ${e?"value = value + getBiasByOutputCoords(coords);":""}
      `}),iu,bc=I(()=>{iu=e=>`
fn getIndexFromCoords4D(coords : vec4<i32>, shape : vec4<i32>) -> i32 {
  return dot(coords, vec4<i32>(
      shape.y * shape.z * shape.w, shape.z * shape.w, shape.w, 1));
}
fn getOutputIndexFromCoords(coords : vec4<i32>) -> i32 {
  return dot(coords, vec4<i32>(
    i32(${e}.x), i32(${e}.y), i32(${e}.z), 1));
}
`}),ta,cn,hn=I(()=>{ue(),oe(),Z(),Fr(),ta=(e,t,r,i,a)=>{let n=i-r;return`
      ${Array.from({length:r}).map((s,o)=>`
      if (${D(t.shape,o,t.rank)} != 1) {
        ${t.indicesSet(e,o,D(a,o+n,i))}
      } else {
        ${t.indicesSet(e,o,0)}
      }`).join("")}
`},cn=(e,t,r,i,a=!1,n)=>{let s=e[0].dims,o=e[1].dims,u=s[s.length-2],l=o[o.length-1],d=s[s.length-1],p=A(l),h=A(d),f=A(u),m=M.size(r)/p/f,w=e.length>2,$=i?i.slice(0,-2):r.slice(0,-2),_=[M.size($),u,l],y=[{type:12,data:m},{type:12,data:u},{type:12,data:l},{type:12,data:d}];Vr(t,y),y.push(...k($,s,o)),w&&y.push(...k(e[2].dims)),y.push(...k(_));let S=v=>{let E=xe("batch_dims",e[0].dataType,$.length),B=z("a",e[0].dataType,s.length,h),R=z("b",e[1].dataType,o.length,p),U=q("output",e[0].dataType,_.length,p),W=O(U.type.tensor),X=Lr(t,U.type.value,W),ke=[B,R],ae="";if(w){let j=a?p:1;ke.push(z("bias",e[2].dataType,e[2].dims.length,j)),ae=`${a?`value += bias[col / ${j}];`:`value += ${U.type.value}(bias[row + i]);`}`}let de=[{name:"output_size",type:"u32"},{name:"M",type:"u32"},{name:"N",type:"u32"},{name:"K",type:"u32"}];qr(t,de);let Me=()=>{let j=`var a_data: ${B.type.value};`;for(let re=0;re<h;re++)j+=`
              let b_data${re} = b[(b_offset + (k + ${re}) * uniforms.N + col) / ${p}];`;for(let re=0;re<f;re++){j+=`a_data = a[(a_offset + (row + ${re}) * uniforms.K + k) / ${h}];`;for(let Ie=0;Ie<h;Ie++)j+=`
            values[${re}] = fma(${R.type.value}(a_data${h===1?"":`[${Ie}]`}), b_data${Ie}, values[${re}]);
`}return j};return`
  ${v.registerUniforms(de).registerInternalVariables(E).declareVariables(...ke,U)}
  ${v.mainStart()}
    ${v.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
    let col = (global_idx % (uniforms.N / ${p})) * ${p};
    var index1 = global_idx / (uniforms.N / ${p});
    let stride1 = uniforms.M / ${f};
    let row = (index1 % stride1) * ${f};
    let batch = index1 / stride1;

    ${r.length===2?"":`let batch_indices = ${E.offsetToIndices("batch")};`}

    var a_indices: ${B.type.indices};
    ${ta("a_indices",B,B.rank-2,E.rank,"batch_indices")}
    ${B.indicesSet("a_indices",B.rank-2,0)}
    ${B.indicesSet("a_indices",B.rank-1,0)}
    let a_offset = ${B.indicesToOffset("a_indices")};

    var b_indices: ${R.type.indices};
    ${ta("b_indices",R,R.rank-2,E.rank,"batch_indices")}
    ${R.indicesSet("b_indices",R.rank-2,0)}
    ${R.indicesSet("b_indices",R.rank-1,0)}
    let b_offset = ${R.indicesToOffset("b_indices")};
    var values: array<${U.type.value}, ${f}>;
    for (var k: u32 = 0u; k < uniforms.K; k = k + ${h}) {
      ${Me()}
    }
    for (var i = 0u; i < ${f}u; i++) {
      var value = values[i];
      ${ae}
      ${X}
      let cur_indices = ${U.type.indices}(batch, row + i, col);
      let offset = ${U.indicesToOffset("cur_indices")};
      ${U.setByOffset(`offset / ${p}`,"value")};
    }
  }
  `};return{name:"MatMulNaive",shaderCache:{hint:`${t.activation};${p};${h};${f};${a}`,inputDependencies:w?["rank","rank","rank"]:["rank","rank"]},getRunData:()=>({outputs:[{dims:n?n(r):r,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(m/64)},programUniforms:y}),getShaderSource:S}}}),au,nu,fn,mn,su,gn,ou,za,yn=I(()=>{ue(),oe(),Z(),Fr(),hn(),pn(),au=(e,t)=>e?`
        mm_Asub[inputRow][inputCol] = mm_readA(batch,
          kStart + inputRow,
          globalRowStart / innerElementSize + inputCol${t?", batchIndices":""});
        `:`
        mm_Asub[inputRow][inputCol] = mm_readA(batch,
          globalRow + innerRow,
          kStart / innerElementSize + inputCol${t?", batchIndices":""});
        `,nu=(e,t)=>e?`
        let ACached0 = mm_Asub[k * innerElementSize][localRow];
        let ACached1 = mm_Asub[k * innerElementSize + 1][localRow];
        let ACached2 = mm_Asub[k * innerElementSize + 2][localRow];
        ${t===3?"":"let ACached3 = mm_Asub[k * innerElementSize + 3][localRow];"}
        for (var i = 0; i < rowPerThread; i = i + 1) {
          acc[i] = BCached0 * ACached0[i] + acc[i];
          acc[i] = BCached1 * ACached1[i] + acc[i];
          acc[i] = BCached2 * ACached2[i] + acc[i];
          ${t===3?"":"acc[i] = BCached3 * ACached3[i] + acc[i];"}
        }`:`
        for (var i = 0; i < rowPerThread; i = i + 1) {
          let ACached = mm_Asub[tileRow + i][k];
          acc[i] = BCached0 * ACached.x + acc[i];
          acc[i] = BCached1 * ACached.y + acc[i];
          acc[i] = BCached2 * ACached.z + acc[i];
          ${t===3?"":"acc[i] = BCached3 * ACached.w + acc[i];"}
        }`,fn=(e,t,r="f32",i,a=!1,n=32,s=!1,o=32)=>{let u=t[1]*e[1],l=t[0]*e[0],d=a?u:n,p=a?n:u,h=d/t[0],f=n/t[1];if(!((a&&h===4&&e[1]===4||!a&&(h===3||h===4))&&d%t[0]===0&&n%t[1]===0&&e[0]===4))throw new Error(`If transposeA ${a} is true, innerElementSize ${h} and workPerThread[1] ${e[1]} must be 4.
      Otherwise, innerElementSize ${h} must be 3 or 4.
  tileAWidth ${d} must be divisible by workgroupSize[0]${t[0]}. tileInner ${n} must be divisible by workgroupSize[1] ${t[1]}. colPerThread ${e[0]} must be 4.`);return`
var<workgroup> mm_Asub: array<array<vec${h}<${r}>, ${d/h}>, ${p}>;
var<workgroup> mm_Bsub: array<array<vec4<${r}>, ${l/e[0]}>, ${n}>;

const rowPerThread = ${e[1]};
const colPerThread = ${e[0]};
const innerElementSize = ${h};
const tileInner = ${n};

@compute @workgroup_size(${t[0]}, ${t[1]}, ${t[2]})
fn main(@builtin(local_invocation_id) localId : vec3<u32>,
        @builtin(global_invocation_id) globalId : vec3<u32>,
        @builtin(workgroup_id) workgroupId : vec3<u32>) {
  let localRow = i32(localId.y);
  let tileRow = localRow * rowPerThread;
  let tileCol = i32(localId.x);

  let globalRow =i32(globalId.y) * rowPerThread;
  let globalCol = i32(globalId.x);
  let batch = ${s?"0":"i32(globalId.z)"};
  ${i?`let batchIndices = ${i.offsetToIndices("u32(batch)")};`:""}
  let globalRowStart = i32(workgroupId.y) * ${u};

  let num_tiles = ${s?`${Math.ceil(o/n)}`:"(uniforms.dim_inner - 1) / tileInner + 1"};
  var kStart = ${s?`i32(globalId.z) * ${o}`:"0"};

  var acc: array<vec4<${r}>, rowPerThread>;

  // Loop over shared dimension.
  let tileRowB = localRow * ${f};
  for (var t = 0; t < num_tiles; t = t + 1) {
      // Load one tile of A into local memory.
      for (var innerRow = 0; innerRow < rowPerThread; innerRow = innerRow + 1) {
          let inputRow = tileRow + innerRow;
          let inputCol = tileCol;
          ${au(a,i)}
      }

      // Load one tile of B into local memory.
      for (var innerRow = 0; innerRow < ${f}; innerRow = innerRow + 1) {
          let inputRow = tileRowB + innerRow;
          let inputCol = tileCol;
          mm_Bsub[inputRow][inputCol] = mm_readB(batch, kStart + inputRow, globalCol${i?", batchIndices":""});
      }
      kStart = kStart + tileInner;
      workgroupBarrier();

      // Compute acc values for a single thread.
      for (var k = 0; k < tileInner / innerElementSize; k = k + 1) {
          let BCached0 = mm_Bsub[k * innerElementSize][tileCol];
          let BCached1 = mm_Bsub[k * innerElementSize + 1][tileCol];
          let BCached2 = mm_Bsub[k * innerElementSize + 2][tileCol];
          ${h===3?"":"let BCached3 = mm_Bsub[k * innerElementSize + 3][tileCol];"}

          ${nu(a,h)}
      }

      workgroupBarrier();
  }

  for (var innerRow = 0; innerRow < rowPerThread; innerRow = innerRow + 1) {
      mm_write(batch, globalRow + innerRow, globalCol, acc[innerRow]);
  }
}`},mn=(e,t)=>e?`
            mm_Asub[inputRow][inputCol] = mm_readA(batch,
              kStart + inputRow,
              globalRowStart + inputCol${t?", batchIndices":""});
            `:`
            mm_Asub[inputRow][inputCol] = mm_readA(batch,
              globalRowStart + inputRow,
              kStart + inputCol${t?", batchIndices":""});
            `,su=e=>e?"let ACached = mm_Asub[k][tileRow + innerRow];":"let ACached = mm_Asub[tileRow + innerRow][k];",gn=(e,t,r="f32",i,a=!1,n=32,s=!1,o=32,u=!1)=>{let l=e[1]*t[1],d=e[0]*t[0],p=a?l:n,h=a?n:l;if(!(h%t[1]===0&&p%t[0]===0&&n%t[1]===0))throw new Error(`tileAHight ${h} must be divisible by workgroupSize[1]${t[1]}, tileAWidth ${p} must be divisible by workgroupSize[0]${t[0]}, tileInner ${n} must be divisible by workgroupSize[1]${t[1]}`);let f=h/t[1],m=p/t[0],w=n/t[1],$=u?`
    let localRow = i32(localId.y);
    let localCol = i32(localId.x);
    let globalRowStart = i32(workgroupId.y) * ${l};
    let globalColStart = i32(workgroupId.x) * ${d};

    // Loop over shared dimension.
    for (var t = 0; t < num_tiles; t = t + 1) {
      // Load one tile of A into local memory.
      for (var inputRow = localRow; inputRow < ${h}; inputRow = inputRow + ${t[1]}) {
        for (var inputCol = localCol; inputCol < ${p}; inputCol = inputCol + ${t[0]}) {
          ${mn(a,i)}
        }
      }
      // Load one tile of B into local memory.
      for (var inputRow = localRow; inputRow < ${n}; inputRow = inputRow + ${t[1]}) {
            for (var inputCol = localCol; inputCol < ${d}; inputCol = inputCol + ${t[0]}) {
          mm_Bsub[inputRow][inputCol] = mm_readB(batch,
            kStart + inputRow,
            globalColStart + inputCol${i?", batchIndices":""});
        }
      }
      kStart = kStart + tileInner;
      workgroupBarrier();

      // Compute acc values for a single thread.
      var BCached : array<${r}, colPerThread>;
      for (var k = 0; k < tileInner; k = k + 1) {
        for (var inner = 0; inner < colPerThread; inner = inner + 1) {
          BCached[inner] = mm_Bsub[k][localCol + inner * ${t[0]}];
        }
        for (var innerRow = 0; innerRow < rowPerThread; innerRow = innerRow + 1) {
          let ACached = ${a?`mm_Asub[k][localRow + innerRow * ${t[1]}];`:`mm_Asub[localRow + innerRow * ${t[1]}][k];`}
          for (var innerCol = 0; innerCol < colPerThread; innerCol = innerCol + 1) {
            acc[innerRow][innerCol] = acc[innerRow][innerCol] +
                ACached * BCached[innerCol];
          }
        }
      }
      workgroupBarrier();
    }
    for (var innerRow = 0; innerRow < rowPerThread; innerRow = innerRow + 1) {
      let gRow = globalRowStart + localRow + innerRow * ${t[1]};
      for (var innerCol = 0; innerCol < colPerThread; innerCol = innerCol + 1) {
        let gCol = globalColStart + localCol + innerCol * ${t[0]};
        mm_write(batch, gRow, gCol, acc[innerRow][innerCol]);
      }
    }
    `:`
let tileRow = i32(localId.y) * rowPerThread;
let tileCol = i32(localId.x) * colPerThread;

let globalRow = i32(globalId.y) * rowPerThread;
let globalCol = i32(globalId.x) * colPerThread;
let globalRowStart = i32(workgroupId.y) * ${l};

let tileRowA = i32(localId.y) * ${f};
let tileColA = i32(localId.x) * ${m};
let tileRowB = i32(localId.y) * ${w};
// Loop over shared dimension.
for (var t = 0; t < num_tiles; t = t + 1) {
  // Load one tile of A into local memory.
  for (var innerRow = 0; innerRow < ${f}; innerRow = innerRow + 1) {
    for (var innerCol = 0; innerCol < ${m}; innerCol = innerCol + 1) {
      let inputRow = tileRowA + innerRow;
      let inputCol = tileColA + innerCol;
      ${mn(a,i)}
    }
  }

  // Load one tile of B into local memory.
  for (var innerRow = 0; innerRow < ${w}; innerRow = innerRow + 1) {
    for (var innerCol = 0; innerCol < colPerThread; innerCol = innerCol + 1) {
      let inputRow = tileRowB + innerRow;
      let inputCol = tileCol + innerCol;
      mm_Bsub[inputRow][inputCol] = mm_readB(batch,
        kStart + inputRow,
        globalCol + innerCol${i?", batchIndices":""});
    }
  }
  kStart = kStart + tileInner;
  workgroupBarrier();

  // Compute acc values for a single thread.
  var BCached : array<${r}, colPerThread>;
  for (var k = 0; k < tileInner; k = k + 1) {
    for (var inner = 0; inner < colPerThread; inner = inner + 1) {
      BCached[inner] = mm_Bsub[k][tileCol + inner];
    }

    for (var innerRow = 0; innerRow < rowPerThread; innerRow = innerRow + 1) {
      ${su(a)}
      for (var innerCol = 0; innerCol < colPerThread; innerCol = innerCol + 1) {
        acc[innerRow][innerCol] = acc[innerRow][innerCol] + ACached * BCached[innerCol];
      }
    }
  }

  workgroupBarrier();
}

for (var innerRow = 0; innerRow < rowPerThread; innerRow = innerRow + 1) {
  for (var innerCol = 0; innerCol < colPerThread; innerCol = innerCol + 1) {
    mm_write(batch, globalRow + innerRow, globalCol + innerCol,
        acc[innerRow][innerCol]);
  }
}
`;return`
  var<workgroup> mm_Asub : array<array<${r}, ${p}>, ${h}>;
  var<workgroup> mm_Bsub : array<array<${r}, ${d}>, ${n}>;
  const rowPerThread = ${e[1]};
  const colPerThread = ${e[0]};
  const tileInner = ${n};

@compute @workgroup_size(${t[0]}, ${t[1]}, ${t[2]})
fn main(@builtin(local_invocation_id) localId : vec3<u32>,
        @builtin(global_invocation_id) globalId : vec3<u32>,
        @builtin(workgroup_id) workgroupId : vec3<u32>) {
    let batch = ${s?"0":"i32(globalId.z)"};
    ${i?`let batchIndices = ${i.offsetToIndices("u32(batch)")};`:""}
    let num_tiles = ${s?`${Math.ceil(o/n)}`:"(uniforms.dim_inner - 1) / tileInner + 1"};
    var kStart = ${s?`i32(globalId.z) * ${o}`:"0"};

    var acc : array<array<${r}, colPerThread>, rowPerThread>;
    ${$}
  }
`},ou=(e,t,r,i,a=!1)=>{let[n,s,o,u]=i,l=O(i[0].type.tensor);return`
    fn mm_readA(batch: i32, row: i32, colIn: i32, batchIndices: ${n.type.indices}) -> ${at(e,l)} {
      var value = ${at(e,l)}(0.0);
      let col = colIn * ${e};
      if(row < uniforms.dim_a_outer && col < uniforms.dim_inner)
      {
        var aIndices: ${s.type.indices};
        ${ta("aIndices",s,s.rank-2,n.rank,"batchIndices")}
        ${s.indicesSet("aIndices",s.rank-2,"u32(row)")}
        ${s.indicesSet("aIndices",s.rank-1,"u32(colIn)")}
        value = ${s.getByIndices("aIndices")};
      }
      return value;
    }

    fn mm_readB(batch: i32, row: i32, colIn: i32, batchIndices: ${n.type.indices}) -> ${at(e,l)} {
      var value = ${at(e,l)}(0.0);
      let col = colIn * ${e};
      if(row < uniforms.dim_inner && col < uniforms.dim_b_outer)
      {
        var bIndices: ${o.type.indices};
        ${ta("bIndices",o,o.rank-2,n.rank,"batchIndices")}
        ${o.indicesSet("bIndices",o.rank-2,"u32(row)")}
        ${o.indicesSet("bIndices",o.rank-1,"u32(colIn)")}
        value = ${o.getByIndices("bIndices")};
      }
      return value;
    }

    fn mm_write(batch: i32, row: i32, colIn: i32, valueIn: ${at(e,l)}) {
      let col = colIn * ${e};
      if (row < uniforms.dim_a_outer && col < uniforms.dim_b_outer) {
        var value = valueIn;
        let coords = vec3<i32>(batch, row, colIn);
        ${t?`value = value + ${a?"bias[colIn]":`${at(e,l)}(bias[row])`};`:""}
        ${r}
        ${u.setByIndices("vec3<u32>(coords)","value")}
      }
    }
    `},za=(e,t,r,i,a=!1,n)=>{let s=e[0].dims,o=e[1].dims,u=s.slice(0,-2),l=o.slice(0,-2),d=i?i.slice(0,-2):r.slice(0,-2),p=M.size(d),h=s[s.length-2],f=s[s.length-1],m=o[o.length-1],w=f%4===0&&m%4===0,$=h<=8?[4,1,1]:[4,4,1],_=[8,8,1],y=[Math.ceil(m/_[0]/$[0]),Math.ceil(h/_[1]/$[1]),Math.ceil(p/_[2]/$[2])],S=w?4:1,v=[...u,h,f/S],E=v.length,B=[...l,f,m/S],R=B.length,U=[p,h,m/S],W=[{type:6,data:h},{type:6,data:m},{type:6,data:f}];Vr(t,W),W.push(...k(d,v,B));let X=["rank","rank"],ke=e.length>2;ke&&(W.push(...k(e[2].dims)),X.push("rank")),W.push(...k(U));let ae=de=>{let Me=d.length,j=xe("batchDims",e[0].dataType,Me,1),re=O(e[0].dataType),Ie=z("a",e[0].dataType,E,S),be=z("b",e[1].dataType,R,S),fe=q("result",e[0].dataType,U.length,S),De=[Ie,be];if(ke){let Dt=a?S:1;De.push(z("bias",e[2].dataType,e[2].dims.length,Dt))}let L=[{name:"dim_a_outer",type:"i32"},{name:"dim_b_outer",type:"i32"},{name:"dim_inner",type:"i32"}];qr(t,L);let K=O(fe.type.tensor),$e=Lr(t,fe.type.value,K),Pe=ou(S,ke,$e,[j,Ie,be,fe],a);return`
  ${de.registerUniforms(L).registerInternalVariables(j).declareVariables(...De,fe)}
  ${Pe}
  ${w?fn($,_,re,j):gn($,_,re,j)}
                   `};return{name:"MatMul",shaderCache:{hint:`${$};${t.activation};${w};${a}`,inputDependencies:X},getRunData:()=>({outputs:[{dims:n?n(r):r,dataType:e[0].dataType}],dispatchGroup:{x:y[0],y:y[1],z:y[2]},programUniforms:W}),getShaderSource:ae}}}),uu,lu,$c=I(()=>{ue(),yt(),Z(),Fr(),pn(),bc(),yn(),uu=(e,t,r,i,a=!1,n,s=4,o=4,u=4,l="f32")=>{let d=W=>{switch(W){case 1:return"resData = x[xIndex];";case 3:return`resData = vec3<${l}>(x[xIndex], x[xIndex + 1], x[xIndex + 2]);`;case 4:return"resData = x[xIndex / 4];";default:throw new Error(`innerElementSize ${W} is not supported.`)}},p=W=>{switch(W){case 1:return"return w[row * i32(uniforms.w_shape[3]) + colIn];";case 4:return"return w[row * i32(uniforms.w_shape[3]) / 4 + colIn];";default:throw new Error(`innerElementSize ${W} is not supported.`)}},h=e?`
    let coord = vec4<i32>(batch, xRow, xCol, xCh);
    `:`
    let coord = vec4<i32>(batch, xCh, xRow, xCol);
    `,f=e?`
    let coords = vec4<i32>(
      batch,
      row / outWidth,
      row % outWidth,
      col);
    `:`
    let coords = vec4<i32>(
      batch,
      row,
      col / outWidth,
      col % outWidth);
    `,m=e?"i32(uniforms.x_shape[1])":"i32(uniforms.x_shape[2])",w=e?"i32(uniforms.x_shape[2])":"i32(uniforms.x_shape[3])",$=e?"row":"col",_=e?"col":"row",y=`
    let inChannels = i32(uniforms.w_shape[2]);
    let outWidth = ${e?"i32(uniforms.result_shape[2])":"i32(uniforms.result_shape[3])"};
    let outRow = ${$} / outWidth;
    let outCol = ${$} % outWidth;

    let WRow = ${_} / (i32(uniforms.w_shape[1]) * inChannels);
    let WCol = ${_} / inChannels % i32(uniforms.w_shape[1]);
    let xRow = outRow * uniforms.stride[0] + uniforms.dilation[0] * WRow - uniforms.pad[0];
    let xCol = outCol * uniforms.stride[1] + uniforms.dilation[1] * WCol - uniforms.pad[1];
    let xCh = ${_} % inChannels;
    var resData = ${at(s,l)}(0.0);
    // The bounds checking is always needed since we use it to pad zero for
    // the 'same' padding type.
    if (xRow >= 0 && xRow < ${m} && xCol >= 0 && xCol < ${w}) {
      ${h}
      let xIndex = getIndexFromCoords4D(coord, vec4<i32>(uniforms.x_shape));
      ${d(s)}
    }
    return resData;`,S=e?t&&i?`
    let col = colIn * ${s};
    ${y}`:`
    let col = colIn * ${s};
    if (row < uniforms.dim_a_outer && col < uniforms.dim_inner) {
      ${y}
    }
    return ${at(s,l)}(0.0);`:i&&r?`
    let col = colIn * ${s};
    ${y}`:`
    let col = colIn * ${s};
    if (row < uniforms.dim_inner && col < uniforms.dim_b_outer) {
      ${y}
    }
    return ${at(s,l)}(0.0);`,v=e?i&&r?p(o):`
    let col = colIn * ${o};
    if (row < uniforms.dim_inner && col < uniforms.dim_b_outer) {
      ${p(o)}
    }
    return ${at(o,l)}(0.0);`:`
    let col = colIn * ${o};
    if (row < uniforms.dim_inner && col < uniforms.dim_a_outer) {
      ${p(o)}
    }
    return ${at(o,l)}(0.0);`,E=at(u,l),B=at(e?s:o,l),R=at(e?o:s,l),U=Lr(n,E,l);return`
    fn mm_readA(batch: i32, row : i32, colIn : i32) -> ${B} {
      ${e?S:v}
    }

    fn mm_readB(batch: i32, row : i32, colIn : i32) -> ${R} {
      ${e?v:S}
    }

    fn mm_write(batch: i32, row : i32, colIn : i32, valueIn : ${E}) {
      let col = colIn * ${u};
      if (row < uniforms.dim_a_outer && col < uniforms.dim_b_outer)
      {
      var value = valueIn;
      let outWidth = ${e?"i32(uniforms.result_shape[2])":"i32(uniforms.result_shape[3])"};
      ${f}
      ${ru(a)}
      ${U}
      setOutputAtCoords(coords[0], coords[1], coords[2], coords[3], value);
      }
    }`},lu=(e,t,r,i,a,n,s,o,u)=>{let l=t.format==="NHWC",d=l?e[0].dims[3]:e[0].dims[1],p=r[0],h=l?r[2]:r[3],f=l?r[1]:r[2],m=l?r[3]:r[1],w=l&&(d%4===0||d%3===0)&&m%4===0,$=l?m:h*f,_=l?h*f:m,y=[8,8,1],S=i<=8?[4,1,1]:[4,4,1],v=[Math.ceil($/y[0]/S[0]),Math.ceil(_/y[1]/S[1]),Math.ceil(p/y[2]/S[2])];Ae("verbose",()=>`[conv2d_mm_webgpu] dispatch = ${v}`);let E=w?l&&d%4!==0?3:4:1,B=y[1]*S[1],R=y[0]*S[0],U=Math.max(y[0]*E,y[1]),W=i%B===0,X=a%R===0,ke=n%U===0,ae=w?[E,4,4]:[1,1,1],de=[{type:6,data:i},{type:6,data:a},{type:6,data:n},{type:6,data:[t.pads[0],t.pads[1]]},{type:6,data:t.strides},{type:6,data:t.dilations}];Vr(t,de),de.push(...k(e[0].dims,e[1].dims));let Me=["rank","rank"];s&&(de.push(...k(e[2].dims)),Me.push("rank")),de.push(...k(r));let j=re=>{let Ie=[{name:"dim_a_outer",type:"i32"},{name:"dim_b_outer",type:"i32"},{name:"dim_inner",type:"i32"},{name:"pad",type:"i32",length:2},{name:"stride",type:"i32",length:2},{name:"dilation",type:"i32",length:2}];qr(t,Ie);let be=w?4:1,fe=O(e[0].dataType),De=`
      fn setOutputAtIndex(flatIndex : i32, value : ${w?`vec4<${fe}>`:fe}) {
        result[flatIndex] = ${w?`vec4<${fe}>`:fe}(value);
      }
      fn setOutputAtCoords(d0 : i32, d1 : i32, d2 : i32, d3 : i32, value : ${w?`vec4<${fe}>`:fe}) {
        let flatIndex = getOutputIndexFromCoords(vec4<i32>(d0, d1, d2, d3));
        setOutputAtIndex(flatIndex ${w?"/ 4":""}, value);
      }`,L=z("x",e[0].dataType,e[0].dims.length,E===3?1:E),K=z("w",e[1].dataType,e[1].dims.length,be),$e=[L,K],Pe=q("result",e[0].dataType,r.length,be);if(s){let Dt=z("bias",e[2].dataType,e[2].dims.length,be);$e.push(Dt),De+=`
        fn getBiasByOutputCoords(coords : vec4<i32>) -> ${w?`vec4<${fe}>`:fe} {
          return bias[coords.${l?"w":"y"}${w?"/ 4":""}];
        }`}return`
        ${iu("uniforms.result_strides")}
        //struct Uniforms { xShape : vec4<i32>, wShape : vec4<i32>, outShape : vec4<i32>,
        //  outShapeStrides: vec3<i32>, filterDims : vec2<i32>, pad : vec2<i32>, stride : vec2<i32>,
        //  dilation : vec2<i32>, dimAOuter : i32, dimBOuter : i32, dimInner : i32 };
        ${re.registerUniforms(Ie).declareVariables(...$e,Pe)}
        ${De}
        ${uu(l,W,X,ke,s,t,ae[0],ae[1],ae[2],fe)}
        ${w?fn(S,y,fe,void 0,!l,U):gn(S,y,fe,void 0,!l,U,!1,void 0,o)}`};return{name:"Conv2DMatMul",shaderCache:{hint:`${t.cacheKey};${E};${w};${W};${X};${ke};${B};${R};${U}`,inputDependencies:Me},getRunData:()=>({outputs:[{dims:u?u(r):r,dataType:e[0].dataType}],dispatchGroup:{x:v[0],y:v[1],z:v[2]},programUniforms:de}),getShaderSource:j}}}),du,wn,ra,pu,_n,cu,hu,fu,vc=I(()=>{ue(),yt(),oe(),Z(),Fr(),pn(),du=e=>{let t=1;for(let r=0;r<e.length;r++)t*=e[r];return t},wn=e=>typeof e=="number"?[e,e,e]:e,ra=(e,t)=>t<=1?e:e+(e-1)*(t-1),pu=(e,t,r,i=1)=>{let a=ra(t,i);return Math.floor((e[0]*(r-1)-r+a)/2)},_n=(e,t,r,i,a)=>{a==null&&(a=pu(e,t[0],i[0]));let n=[0,0,0,r];for(let s=0;s<3;s++)e[s]+2*a>=t[s]&&(n[s]=Math.trunc((e[s]-t[s]+2*a)/i[s]+1));return n},cu=(e,t,r,i,a,n,s,o,u,l)=>{let d,p,h,f;if(e==="VALID"&&(e=0),typeof e=="number"){d={top:e,bottom:e,left:e,right:e,front:e,back:e};let m=_n([t,r,i,1],[o,u,l],1,[a,n,s],e);p=m[0],h=m[1],f=m[2]}else if(Array.isArray(e)){if(!e.every((w,$,_)=>w===_[0]))throw Error(`Unsupported padding parameter: ${e}`);d={top:e[0],bottom:e[1],left:e[2],right:e[3],front:e[4],back:e[5]};let m=_n([t,r,i,1],[o,u,l],1,[a,n,s],e[0]);p=m[0],h=m[1],f=m[2]}else if(e==="SAME_UPPER"){p=Math.ceil(t/a),h=Math.ceil(r/n),f=Math.ceil(i/s);let m=(p-1)*a+o-t,w=(h-1)*n+u-r,$=(f-1)*s+l-i,_=Math.floor(m/2),y=m-_,S=Math.floor(w/2),v=w-S,E=Math.floor($/2),B=$-E;d={top:S,bottom:v,left:E,right:B,front:_,back:y}}else throw Error(`Unknown padding parameter: ${e}`);return{padInfo:d,outDepth:p,outHeight:h,outWidth:f}},hu=(e,t,r,i,a,n=!1,s="channelsLast")=>{let o,u,l,d,p;if(s==="channelsLast")[o,u,l,d,p]=e;else if(s==="channelsFirst")[o,p,u,l,d]=e;else throw new Error(`Unknown dataFormat ${s}`);let[h,,f,m,w]=t,[$,_,y]=wn(r),[S,v,E]=wn(i),B=ra(f,S),R=ra(m,v),U=ra(w,E),{padInfo:W,outDepth:X,outHeight:ke,outWidth:ae}=cu(a,u,l,d,$,_,y,B,R,U),de=n?h*p:h,Me=[0,0,0,0,0];return s==="channelsFirst"?Me=[o,de,X,ke,ae]:s==="channelsLast"&&(Me=[o,X,ke,ae,de]),{batchSize:o,dataFormat:s,inDepth:u,inHeight:l,inWidth:d,inChannels:p,outDepth:X,outHeight:ke,outWidth:ae,outChannels:de,padInfo:W,strideDepth:$,strideHeight:_,strideWidth:y,filterDepth:f,filterHeight:m,filterWidth:w,effectiveFilterDepth:B,effectiveFilterHeight:R,effectiveFilterWidth:U,dilationDepth:S,dilationHeight:v,dilationWidth:E,inShape:e,outShape:Me,filterShape:t}},fu=(e,t,r,i,a,n)=>{let s=n==="channelsLast";s?e[0].dims[3]:e[0].dims[1];let o=[64,1,1],u={x:r.map(($,_)=>_)},l=[Math.ceil(du(u.x.map($=>r[$]))/o[0]),1,1];Ae("verbose",()=>`[conv3d_naive_webgpu] dispatch = ${l}`);let d=1,p=M.size(r),h=[{type:12,data:p},{type:12,data:i},{type:12,data:a},{type:12,data:t.strides},{type:12,data:t.dilations}];Vr(t,h),h.push(...k(e[0].dims,e[1].dims));let f=["rank","rank"],m=e.length===3;m&&(h.push(...k(e[2].dims)),f.push("rank")),h.push(...k(r));let w=$=>{let _=[{name:"output_size",type:"u32"},{name:"filter_dims",type:"u32",length:i.length},{name:"pads",type:"u32",length:a.length},{name:"strides",type:"u32",length:t.strides.length},{name:"dilations",type:"u32",length:t.dilations.length}];qr(t,_);let y=1,S=O(e[0].dataType),v=z("x",e[0].dataType,e[0].dims.length,d),E=z("W",e[1].dataType,e[1].dims.length,y),B=[v,E],R=q("result",e[0].dataType,r.length,y),U="";if(m){let ke=z("bias",e[2].dataType,e[2].dims.length,y);B.push(ke),U+=`
        fn getBiasByOutputCoords(coords : array<u32, 5>) -> ${S} {
          return bias[${s?D("coords",4,5):D("coords",1,5)}];
        }`}let W=at(d,S),X=Lr(t,W,S);return`
            ${U}
            fn getX(d0 : u32, d1 : u32, d2 : u32, d3 : u32, d4 : u32) -> f32 {
              let aIndices = array<u32, 5>(d0, d1, d2, d3, d4);
              return ${v.getByIndices("aIndices")};
            }
            fn getW(d0 : u32, d1 : u32, d2 : u32, d3 : u32, d4 : u32) -> f32 {
              let aIndices = array<u32, 5>(d0, d1, d2, d3, d4);
              return ${E.getByIndices("aIndices")};
            }
          ${$.registerUniforms(_).declareVariables(...B,R)}
          ${$.mainStart()}
          ${$.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
              let coords = ${R.offsetToIndices("global_idx")};
              let batch = ${D("coords",0,v.rank)};
              let d2 = ${s?D("coords",v.rank-1,v.rank):D("coords",1,v.rank)};
              let xFRCCorner = vec3<u32>(${s?D("coords",1,v.rank):D("coords",2,v.rank)},
              ${s?D("coords",2,v.rank):D("coords",3,v.rank)},
              ${s?D("coords",3,v.rank):D("coords",4,v.rank)}) * uniforms.strides - uniforms.pads;
              let xFCorner = xFRCCorner.x;
              let xRCorner = xFRCCorner.y;
              let xCCorner = xFRCCorner.z;
              let xShapeY = ${s?D("uniforms.x_shape",1,v.rank):D("uniforms.x_shape",2,v.rank)};
              let xShapeZ = ${s?D("uniforms.x_shape",2,v.rank):D("uniforms.x_shape",3,v.rank)};
              let xShapeW = ${s?D("uniforms.x_shape",3,v.rank):D("uniforms.x_shape",4,v.rank)};
              let xShapeU = ${s?D("uniforms.x_shape",4,v.rank):D("uniforms.x_shape",1,v.rank)};
              let inputDepthNearestVec4 = (xShapeU / 4) * 4;
              let inputDepthVec4Remainder = xShapeU % 4;

              var value = 0.0;
              for (var wF = 0u; wF < uniforms.filter_dims[0]; wF++) {
                let xF = xFCorner + wF * uniforms.dilations[0];
                if (xF < 0 || xF >= xShapeY) {
                  continue;
                }

                for (var wR = 0u; wR < uniforms.filter_dims[1]; wR++) {
                  let xR = xRCorner + wR * uniforms.dilations[1];
                  if (xR < 0 || xR >= xShapeZ) {
                    continue;
                  }

                  for (var wC = 0u; wC < uniforms.filter_dims[2]; wC++) {
                    let xC = xCCorner + wC * uniforms.dilations[2];
                    if (xC < 0 || xC >= xShapeW) {
                      continue;
                    }

                    for (var d1 = 0u; d1 < inputDepthNearestVec4; d1 += 4) {
                      ${s?`let xValues = vec4<f32>(
                               getX(batch, xF, xR, xC, d1),
                               getX(batch, xF, xR, xC, d1 + 1),
                               getX(batch, xF, xR, xC, d1 + 2),
                               getX(batch, xF, xR, xC, d1 + 3));
                            `:`let xValues = vec4<f32>(
                               getX(batch, d1, xF, xR, xC),
                               getX(batch, d1 + 1, xF, xR, xC),
                               getX(batch, d1 + 2, xF, xR, xC),
                               getX(batch, d1 + 3, xF, xR, xC));
                            `}
                            let wValues = vec4<f32>(
                              getW(d2, d1, wF, wR, wC),
                              getW(d2, d1 + 1, wF, wR, wC),
                              getW(d2, d1 + 2, wF, wR, wC),
                              getW(d2, d1 + 3, wF, wR, wC));
                      value += dot(xValues, wValues);
                    }
                    if (inputDepthVec4Remainder == 1) {
                        ${s?`value += getX(batch, xF, xR, xC, inputDepthNearestVec4)
                          * getW(d2, inputDepthNearestVec4, wF, wR, wC);`:`value += getX(batch, inputDepthNearestVec4, xF, xR, xC)
                          * getW(d2, inputDepthNearestVec4, wF, wR, wC);`}
                    } else if (inputDepthVec4Remainder == 2) {
                      ${s?`let xValues = vec2<f32>(
                        getX(batch, xF, xR, xC, inputDepthNearestVec4),
                        getX(batch, xF, xR, xC, inputDepthNearestVec4 + 1));
                      `:`let xValues = vec2<f32>(
                        getX(batch, inputDepthNearestVec4, xF, xR, xC),
                        getX(batch, inputDepthNearestVec4 + 1, xF, xR, xC));
                    `}
                    let wValues = vec2<f32>(
                      getW(d2, inputDepthNearestVec4, wF, wR, wC),
                      getW(d2, inputDepthNearestVec4 + 1, wF, wR, wC));
                      value += dot(xValues, wValues);
                    } else if (inputDepthVec4Remainder == 3) {
                      ${s?`let xValues = vec3<f32>(
                        getX(batch, xF, xR, xC, inputDepthNearestVec4),
                        getX(batch, xF, xR, xC, inputDepthNearestVec4 + 1),
                        getX(batch, xF, xR, xC, inputDepthNearestVec4 + 2));
                      `:`let xValues = vec3<f32>(
                        getX(batch, inputDepthNearestVec4, xF, xR, xC),
                        getX(batch, inputDepthNearestVec4 + 1, xF, xR, xC),
                        getX(batch, inputDepthNearestVec4 + 2, xF, xR, xC));
                    `}
                    let wValues = vec3<f32>(
                      getW(d2, inputDepthNearestVec4, wF, wR, wC),
                      getW(d2, inputDepthNearestVec4 + 1, wF, wR, wC),
                      getW(d2, inputDepthNearestVec4 + 2, wF, wR, wC));
                      value += dot(xValues, wValues);
                    }
                  }
                }
              }
              ${m?"value = value + getBiasByOutputCoords(coords)":""};
              ${X}
              result[global_idx] = f32(value);
          }`};return{name:"Conv3DNaive",shaderCache:{hint:`${t.cacheKey};${s};${d};${m}`,inputDependencies:f},getRunData:()=>({outputs:[{dims:r,dataType:e[0].dataType}],dispatchGroup:{x:l[0],y:l[1],z:l[2]},programUniforms:h}),getShaderSource:w}}}),mu,gu,xc=I(()=>{ue(),oe(),Z(),Fr(),mu=(e,t,r,i)=>{let a=e.length>2,n=a?"value += b[output_channel];":"",s=e[0].dims,o=e[1].dims,u=t.format==="NHWC",l=u?r[3]:r[1],d=l/t.group,p=u&&d>=4?A(l):1,h=M.size(r)/p,f=[{type:12,data:h},{type:12,data:t.dilations},{type:12,data:[t.strides[0],t.strides[1]]},{type:12,data:[t.pads[0],t.pads[1]]},{type:12,data:d}];Vr(t,f),f.push(...k(s,[o[0],o[1],o[2],o[3]/p]));let m=a?["rank","rank","rank"]:["rank","rank"];f.push(...k([r[0],r[1],r[2],r[3]/p]));let w=$=>{let _=q("output",e[0].dataType,r.length,p),y=O(_.type.tensor),S=Lr(t,_.type.value,y),v=z("x",e[0].dataType,s.length),E=z("w",e[1].dataType,o.length,p),B=[v,E];a&&B.push(z("b",e[2].dataType,e[2].dims,p));let R=[{name:"output_size",type:"u32"},{name:"dilations",type:"u32",length:t.dilations.length},{name:"strides",type:"u32",length:2},{name:"pads",type:"u32",length:2},{name:"output_channels_per_group",type:"u32"}];qr(t,R);let U=u?`
      for (var wHeight: u32 = 0u; wHeight < uniforms.w_shape[0]; wHeight++) {
        let xHeight = xRCCorner.x + wHeight * uniforms.dilations[0];

        if (xHeight < 0u || xHeight >= uniforms.x_shape[1]) {
          continue;
        }

        for (var wWidth: u32 = 0u; wWidth < uniforms.w_shape[1]; wWidth++) {
          let xWidth = xRCCorner.y + wWidth * uniforms.dilations[1];
          if (xWidth < 0u || xWidth >= uniforms.x_shape[2]) {
            continue;
          }

          for (var wInChannel: u32 = 0u; wInChannel < uniforms.w_shape[2]; wInChannel++) {
            let input_channel = in_channel_offset + wInChannel;
            let xVal = ${v.get("batch","xHeight","xWidth","input_channel")};
            let wVal = ${E.get("wHeight","wWidth","wInChannel","output_channel")};
            value += xVal * wVal;
          }
        }
      }
      `:`
      for (var wInChannel: u32 = 0u; wInChannel < uniforms.w_shape[1]; wInChannel++) {
        let input_channel = in_channel_offset + wInChannel;
        for (var wHeight: u32 = 0u; wHeight < uniforms.w_shape[2]; wHeight++) {
          let xHeight = xRCCorner.x + wHeight * uniforms.dilations[0];

          if (xHeight < 0u || xHeight >= uniforms.x_shape[2]) {
            continue;
          }

          for (var wWidth: u32 = 0u; wWidth < uniforms.w_shape[3]; wWidth++) {
            let xWidth = xRCCorner.y + wWidth * uniforms.dilations[1];
            if (xWidth < 0u || xWidth >= uniforms.x_shape[3]) {
              continue;
            }

            let xVal = ${v.get("batch","input_channel","xHeight","xWidth")};
            let wVal = ${E.get("output_channel","wInChannel","wHeight","wWidth")};
            value += xVal * wVal;
          }
        }
      }
      `;return`
  ${$.registerUniforms(R).declareVariables(...B,_)}

  ${$.mainStart()}
    ${$.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}

    let outputIndices = ${_.offsetToIndices("global_idx")};
    let batch: u32 = outputIndices[0];
    let output_channel: u32 = outputIndices[${u?3:1}];
    let xRCCorner: vec2<u32> = vec2<u32>(outputIndices[${u?1:2}], outputIndices[${u?2:3}]) * uniforms.strides - uniforms.pads;
    let group_id: u32 = output_channel * ${p} / uniforms.output_channels_per_group;
    var in_channel_offset = group_id * uniforms.w_shape[${u?2:1}];

    var value: ${_.type.value} = ${_.type.value}(0);
    ${U}
    ${n}
    ${S}
    ${_.setByOffset("global_idx","value")}
  }`};return{name:"GroupedConv",shaderCache:{hint:`${t.cacheKey}_${p}`,inputDependencies:m},getRunData:()=>({outputs:[{dims:i?i(r):r,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(h/64)},programUniforms:f}),getShaderSource:w}},gu=(e,t,r,i)=>{let a=e.length>2,n=A(r[3]),s=A(r[2]),o=M.size(r)/n/s,u=[e[0].dims[0],e[0].dims[1],e[0].dims[2],e[0].dims[3]/n],l=[e[1].dims[0],e[1].dims[1],e[1].dims[2],e[1].dims[3]/n],d=[r[0],r[1],r[2],r[3]/n],p=[{type:12,data:o},{type:6,data:[t.strides[0],t.strides[1]]},{type:6,data:[t.pads[0],t.pads[1]]}];Vr(t,p),p.push(...k(u,l,d));let h=(s-1)*t.strides[1]+l[1],f=m=>{let w=q("output",e[0].dataType,d.length,n),$=O(w.type.tensor),_=Lr(t,w.type.value,$),y=z("x",e[0].dataType,u.length,n),S=z("w",e[1].dataType,l.length,n),v=[y,S];a&&v.push(z("b",e[2].dataType,e[2].dims,n));let E=a?"value += b[output_channel];":"",B=[{name:"output_size",type:"u32"},{name:"strides",type:"i32",length:2},{name:"pads",type:"i32",length:2}];return qr(t,B),`
  ${m.registerUniforms(B).declareVariables(...v,w)}
  ${m.mainStart()}
    ${m.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
    let width0 = uniforms.output_shape[3];
    let output_channel = global_idx % width0;
    var index1 = global_idx / width0;
    let width1 = uniforms.output_shape[2] / ${s}u;
    let col = (index1 % width1) * ${s}u;
    index1 = index1 / width1;
    let row = index1 % uniforms.output_shape[1];
    let batch = index1 / uniforms.output_shape[1];

    let x_corner = vec2<i32>(i32(row), i32(col)) * uniforms.strides - uniforms.pads;

    var x_vals: array<${y.type.value}, ${h}>;
    var values: array<${w.type.value}, ${s}>;
    let input_channel = output_channel;
    // Use constant instead of uniform can give better performance for w's height/width.
    for (var w_height: u32 = 0u; w_height < ${l[0]}; w_height++) {
      let x_height = x_corner.x + i32(w_height);
      if (x_height >= 0 && u32(x_height) < uniforms.x_shape[1]) {
        for (var i = 0; i < ${h}; i++) {
          let x_width = x_corner.y + i;
          if (x_width >= 0 && u32(x_width) < uniforms.x_shape[2]) {
            x_vals[i] = ${y.get("batch","u32(x_height)","u32(x_width)","input_channel")};
          } else {
            x_vals[i] = ${y.type.value}(0);
          }
        }
        for (var w_width: u32 = 0u; w_width < ${l[1]}; w_width++) {
          let w_val = ${S.get("w_height","w_width","0","output_channel")};
          for (var i = 0u; i < ${s}u; i++) {
            values[i] = fma(x_vals[i * u32(uniforms.strides[1]) + w_width], w_val, values[i]);
          }
        }
      }
    }

    for (var i = 0u; i < ${s}u; i++) {
      var value = values[i];
      ${E}
      ${_}
      ${w.set("batch","row","col + i","output_channel","value")};
    }
  }`};return{name:"GroupedConv-Vectorize",shaderCache:{hint:`${t.cacheKey};${n};${s};${h};${l[0]};${l[1]}`,inputDependencies:a?["rank","rank","type"]:["rank","rank"]},getRunData:()=>({outputs:[{dims:i?i(r):r,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(o/64)},programUniforms:p}),getShaderSource:f}}}),yu,Aa,wu,Oa,bn,$n,_u,bu,vn,Sc=I(()=>{oe(),$c(),vc(),yn(),xc(),Fr(),hn(),Ee(),yu=(e,t,r,i,a,n)=>{let s=e[0],o=e.slice(n?1:2,n?3:4),u=o.length,l=t[0],d=t.slice(2).map((h,f)=>h+(h-1)*(r[f]-1)),p=o.map((h,f)=>h+i[f]+i[f+u]).map((h,f)=>Math.floor((h-d[f]+a[f])/a[f]));return p.splice(0,0,s),p.splice(n?3:1,0,l),p},Aa=[2,3,1,0],wu=(e,t)=>{if(!e||e.length!==2&&e.length!==3)throw new Error("Conv requires 2 or 3 inputs");if(e[0].dims.length>5)throw new Error("greater than 5D is not supported");if(e[0].dims.length!==e[1].dims.length)throw new Error("filter does not have same dimension as input");let r=e[0].dims[t.format==="NHWC"?e[0].dims.length-1:1],i=e[1].dims[1]*t.group;if(r!==i)throw new Error("FILTER_IN_CHANNEL should be equal to DATA_CHANNEL");if(e.length===3&&(e[2].dims.length!==1||e[1].dims[0]!==e[2].dims[0]))throw new Error("invalid bias");let a=e[0].dims.length-2;if(t.dilations.length!==a)throw new Error(`dilations should be ${a}D`);if(t.strides.length!==a)throw new Error(`strides should be ${a}D`);if(t.pads.length!==a*2)throw new Error(`pads should be ${a*2}D`);if(t.kernelShape.length!==0&&t.kernelShape.length!==e[1].dims.length-2)throw new Error("invalid kernel shape")},Oa=(e,t)=>{let r=e.kernelShape.slice();r.length<t[1].dims.length-2&&r.push(...Array(t[1].dims.length-2-r.length).fill(0));for(let n=2;n<t[1].dims.length;++n)r[n-2]===0&&(r[n-2]=t[1].dims[n]);let i=e.pads.slice();rr.adjustPadsBasedOnAutoPad(t[0].dims,e.strides,e.dilations,r,i,e.format==="NHWC",e.autoPad);let a=Object.assign({},e);return Object.assign(a,{kernelShape:r,pads:i}),a},bn=e=>{let t=dn(e),r=e.format,i=["NOTSET","VALID","SAME_UPPER","SAME_LOWER"][e.auto_pad],a=e.dilations,n=e.group,s=e.kernel_shape,o=e.pads,u=e.strides,l=e.w_is_const();return{autoPad:i,format:r,dilations:a,group:n,kernelShape:s,pads:o,strides:u,wIsConst:l,...t,cacheKey:`${e.format};${t.activation};`}},$n=(e,t,r,i)=>{let a=r.format==="NHWC",n=yu(t[0].dims,t[1].dims,r.dilations,r.pads,r.strides,a);if(r.group!==1){let B=[t[0]];if(a){let R=e.kernelCustomData.wT??e.compute(We(t[1],Aa),{inputs:[1],outputs:[r.wIsConst?-2:-1]})[0];r.wIsConst&&!e.kernelCustomData.wT&&(e.kernelCustomData.wT=R),B.push(R)}else B.push(t[1]);t.length===3&&B.push(t[2]),!e.adapterInfo.isArchitecture("ampere")&&a&&t[1].dims[0]===r.group&&t[1].dims[1]===1&&r.dilations[0]===1&&r.dilations[1]===1?e.compute(gu(B,r,n,i),{inputs:B}):e.compute(mu(B,r,n,i),{inputs:B});return}let s=t.length===3,o=t[0].dims[a?1:2],u=t[0].dims[a?2:3],l=t[0].dims[a?3:1],d=t[1].dims[2],p=t[1].dims[3],h=n[a?1:2],f=n[a?2:3],m=n[a?3:1],w=a&&d===o&&p===u&&r.pads[0]===0&&r.pads[1]===0;if(w||d===1&&p===1&&r.dilations[0]===1&&r.dilations[1]===1&&r.strides[0]===1&&r.strides[1]===1&&r.pads[0]===0&&r.pads[1]===0){let B=n[0],R,U,W,X=[];if(a){let de=e.kernelCustomData.wT??e.compute(We(t[1],Aa),{inputs:[1],outputs:[r.wIsConst?-2:-1]})[0];if(r.wIsConst&&!e.kernelCustomData.wT&&(e.kernelCustomData.wT=de),w){let Me=o*u*l;R=t[0].reshape([1,B,Me]),U=de.reshape([1,Me,m]),W=[1,B,m]}else R=t[0].reshape([B,o*u,l]),U=de.reshape([1,l,m]),W=[B,h*f,m];X.push(R),X.push(U)}else R=t[0].reshape([B,l,o*u]),U=t[1].reshape([1,m,l]),W=[B,m,h*f],X.push(U),X.push(R);s&&X.push(t[2]);let ke=W[2],ae=X[0].dims[X[0].dims.length-1];ke<8&&ae<8?e.compute(cn(X,r,n,W,a,i),{inputs:X}):e.compute(za(X,r,n,W,a,i),{inputs:X});return}let $=!0,_=e.kernelCustomData.wT??e.compute(We(t[1],Aa),{inputs:[1],outputs:[r.wIsConst?-2:-1]})[0];r.wIsConst&&!e.kernelCustomData.wT&&(e.kernelCustomData.wT=_);let y=[t[0],_];s&&y.push(t[2]);let S=a?h*f:m,v=a?m:h*f,E=d*p*l;e.compute(lu(y,r,n,S,v,E,s,$,i),{inputs:y})},_u=(e,t)=>{let r=t.format==="NHWC",i=[e.inputs[0].reshape(r?[e.inputs[0].dims[0],1,e.inputs[0].dims[1],e.inputs[0].dims[2]]:[e.inputs[0].dims[0],e.inputs[0].dims[1],1,e.inputs[0].dims[2]]),e.inputs[1].reshape([e.inputs[1].dims[0],e.inputs[1].dims[1],1,e.inputs[1].dims[2]])];e.inputs.length===3&&i.push(e.inputs[2]);let a=[0,t.pads[0],0,t.pads[1]],n=[1].concat(t.strides),s=[1].concat(t.dilations),o=[1].concat(t.kernelShape),u=Oa({...t,pads:a,strides:n,dilations:s,kernelShape:o},i);$n(e,i,u,l=>r?[l[0],l[2],l[3]]:[l[0],l[1],l[3]])},bu=(e,t,r)=>{let i=r.format==="NHWC"?"channelsLast":"channelsFirst",a=Oa(r,t),n=r.autoPad==="NOTSET"?r.pads:r.autoPad,s=hu(t[0].dims,t[1].dims,r.strides,r.dilations,n,!1,i);e.compute(fu(t,a,s.outShape,[s.filterDepth,s.filterHeight,s.filterWidth],[s.padInfo.front,s.padInfo.top,s.padInfo.left],i))},vn=(e,t)=>{if(wu(e.inputs,t),e.inputs[0].dims.length===3)_u(e,t);else if(e.inputs[0].dims.length===5)bu(e,e.inputs,t);else{let r=Oa(t,e.inputs);$n(e,e.inputs,r)}}}),$u,Tc=I(()=>{ue(),yt(),oe(),Z(),$u=(e,t,r)=>{let i=e.length>2,a=t.outputShape,n=t.format==="NHWC",s=t.group,o=e[1].dims,u=o[2]/s,l=o[3],d=n?A(u):1,p=n&&l===1&&u>=4,h=p?Math.floor(u/4)*4:Math.floor(u/d)*d,f=u-h,m=n?A(l):1,w=n?l===1?d:m:1,$=M.size(a)/m,_=[Math.ceil($/64),1,1];Ae("verbose",()=>`[conv2d_backprop_webgpu] dispatch = ${_}`);let y=["rank","rank"],S=[t.strides[0],t.strides[1]],v=[t.kernelShape[n?1:2],t.kernelShape[n?2:3]],E=[t.dilations[0],t.dilations[1]],B=[v[0]+(t.dilations[0]<=1?0:(t.kernelShape[n?1:2]-1)*(t.dilations[0]-1)),v[1]+(t.dilations[1]<=1?0:(t.kernelShape[n?2:3]-1)*(t.dilations[1]-1))],R=[B[0]-1-Math.floor((t.pads[0]+t.pads[2])/2),B[1]-1-Math.floor((t.pads[1]+t.pads[3])/2)],U=[{type:12,data:$},{type:12,data:S},{type:12,data:v},{type:12,data:E},{type:12,data:B},{type:6,data:R},{type:12,data:h},{type:12,data:u},{type:12,data:l},...k(e[0].dims,e[1].dims)];i&&(U.push(...k(e[2].dims)),y.push("rank")),U.push(...k(a));let W=X=>{let ke=[{name:"output_size",type:"u32"},{name:"strides",type:"u32",length:S.length},{name:"filter_dims",type:"u32",length:v.length},{name:"dilations",type:"u32",length:v.length},{name:"effective_filter_dims",type:"u32",length:B.length},{name:"pads",type:"i32",length:R.length},{name:"input_channels_per_group_int",type:"u32"},{name:"input_channels_per_group",type:"u32"},{name:"output_channels_per_group",type:"u32"}],ae=O(e[0].dataType),de=n?1:2,Me=n?2:3,j=n?3:1,re=z("W",e[1].dataType,e[1].dims.length,w),Ie=z("Dy",e[0].dataType,e[0].dims.length,d),be=[Ie,re];i&&be.push(z("bias",e[2].dataType,[a[j]].length,m));let fe=q("result",e[0].dataType,a.length,m),De=()=>{let $e="";if(p)d===4?$e+=`
        let xValue = ${Ie.getByOffset("x_offset")};
        let wValue = ${re.getByOffset("w_offset")};
        dotProd = dotProd + dot(xValue, wValue);
        x_offset += 1u;
        w_offset += 1u;`:d===2?$e+=`
          dotProd = dotProd + dot(vec4<${ae}>(${Ie.getByOffset("x_offset")}, ${Ie.getByOffset("x_offset + 1u")}), vec4<${ae}>(${re.getByOffset("w_offset")}, ${re.getByOffset("w_offset + 1u")}));
          x_offset += 2u;
          w_offset += 2u;`:d===1&&($e+=`
          dotProd = dotProd + dot(vec4<${ae}>(${Ie.getByOffset("x_offset")}, ${Ie.getByOffset("x_offset + 1u")}, ${Ie.getByOffset("x_offset + 2u")}, ${Ie.getByOffset("x_offset + 3u")}), vec4<${ae}>(${re.getByOffset("w_offset")}, ${re.getByOffset("w_offset + 1u")}, ${re.getByOffset("w_offset + 2u")}, ${re.getByOffset("w_offset + 3u")}));
          x_offset += 4u;
          w_offset += 4u;`);else if($e+=`
                  let xValue = ${n?Ie.getByOffset(`${Ie.indicesToOffset(`${Ie.type.indices}(batch, idyR, idyC, inputChannel)`)} / ${d}`):Ie.get("batch","inputChannel","idyR","idyC")};
        `,d===1)$e+=`
          let w_offset = ${re.indicesToOffset(`${re.type.indices}(u32(wRPerm), u32(wCPerm), inputChannel, wOutChannel)`)};
          let wValue = ${re.getByOffset(`w_offset / ${w}`)};
          dotProd = dotProd + xValue * wValue;`;else for(let Pe=0;Pe<d;Pe++)$e+=`
            let wValue${Pe} = ${re.getByOffset(`${re.indicesToOffset(`${re.type.indices}(u32(wRPerm), u32(wCPerm), inputChannel + ${Pe}, wOutChannel)`)} / ${w}`)};
            dotProd = dotProd + xValue[${Pe}] * wValue${Pe};`;return $e},L=()=>{if(f===0)return"";if(!p)throw new Error(`packInputAs4 ${p} is not true.`);let $e="";if(d===1){$e+="dotProd = dotProd";for(let Pe=0;Pe<f;Pe++)$e+=`
            + ${Ie.getByOffset(`x_offset + ${Pe}`)} * ${re.getByOffset(`w_offset + ${Pe}`)}`;$e+=";"}else if(d===2){if(f!==2)throw new Error(`Invalid inputChannelsRemainder ${f}.`);$e+=`
          let xValue = ${Ie.getByOffset("x_offset")};
          let wValue = ${re.getByOffset("w_offset")};
          dotProd = dotProd + dot(xValue, wValue);`}return $e},K=`
            let outputIndices = ${fe.offsetToIndices(`global_idx * ${m}`)};
            let batch = ${fe.indicesGet("outputIndices",0)};
            let d1 = ${fe.indicesGet("outputIndices",j)};
            let r = ${fe.indicesGet("outputIndices",de)};
            let c = ${fe.indicesGet("outputIndices",Me)};
            let dyCorner = vec2<i32>(i32(r), i32(c)) - uniforms.pads;
            let dyRCorner = dyCorner.x;
            let dyCCorner = dyCorner.y;
            let groupId = d1 / uniforms.output_channels_per_group;
            let wOutChannel = d1 - groupId * uniforms.output_channels_per_group;
            // Convolve dy(?, ?, d2) with w(:, :, d1, d2) to compute dx(xR, xC, d1).
            // ? = to be determined. : = across all values in that axis.
            var dotProd = ${fe.type.value}(0.0);
            var wR: u32 = 0;
            if (uniforms.dilations.x == 1) {
              // Minimum wR >= 0 that satisfies (dyRCorner + wR) % (uniforms.strides.x) == 0
              wR = u32(((dyRCorner + i32(uniforms.strides.x) - 1) / i32(uniforms.strides.x)) * i32(uniforms.strides.x) - dyRCorner);
            }
            for (; wR < uniforms.effective_filter_dims.x; wR = wR + 1) {
              if (wR % uniforms.dilations.x != 0) {
                continue;
              }
              let dyR = (${ae}(dyRCorner) + ${ae}(wR)) / ${ae}(uniforms.strides[0]);
              let wRPerm = uniforms.filter_dims.x - 1 - wR / uniforms.dilations.x;
              if (dyR < 0.0 || dyR >= ${ae}(uniforms.Dy_shape[${de}]) || fract(dyR) > 0.0 ||
                  wRPerm < 0) {
                continue;
              }
              let idyR: u32 = u32(dyR);
              var wC: u32 = 0;
              if (uniforms.dilations.y == 1) {
                // Minimum wC >= 0 that satisfies (dyCCorner + wC) % (uniforms.strides.y) == 0
                wC = u32(((dyCCorner + i32(uniforms.strides.y) - 1) / i32(uniforms.strides.y)) * i32(uniforms.strides.y) - dyCCorner);
              }
              for (; wC < uniforms.effective_filter_dims.y; wC = wC + 1) {
                if (wC % uniforms.dilations.y != 0) {
                  continue;
                }
                let dyC = (${ae}(dyCCorner) + ${ae}(wC)) / ${ae}(uniforms.strides.y);
                let wCPerm = uniforms.filter_dims.y - 1 - wC / uniforms.dilations.y;
                if (dyC < 0.0 || dyC >= ${ae}(uniforms.Dy_shape[${Me}]) ||
                    fract(dyC) > 0.0 || wCPerm < 0) {
                  continue;
                }
                let idyC: u32 = u32(dyC);
                var inputChannel = groupId * uniforms.input_channels_per_group;
                ${p?`
                var x_offset = ${Ie.indicesToOffset(`${Ie.type.indices}(batch, idyR, idyC, inputChannel)`)} / ${d};
                var w_offset = ${re.indicesToOffset(`${re.type.indices}(wRPerm, wCPerm, inputChannel, wOutChannel)`)} / ${w};
                  `:""}
                for (var d2: u32 = 0; d2 < uniforms.input_channels_per_group_int; d2 = d2 + ${p?4:d}) {
                  ${De()}
                  inputChannel = inputChannel + ${p?4:d};
                }
                ${L()}
                wC = wC + uniforms.strides.y - 1;
              }
              wR = wR + uniforms.strides[0] - 1;
            }
            let value = dotProd${i?` + bias[d1 / ${m}]`:""};
            ${fe.setByOffset("global_idx","value")};
          `;return`
    ${X.registerUniforms(ke).declareVariables(...be,fe)}
      ${X.mainStart()}
      ${X.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")};
    ${K}}`};return{name:"ConvTranspose2D",shaderCache:{hint:`${t.cacheKey};${d}${w}${m}${p}${f}`,inputDependencies:y},getRunData:()=>({dispatchGroup:{x:_[0],y:_[1],z:_[2]},outputs:[{dims:r?r(a):a,dataType:e[0].dataType}],programUniforms:U}),getShaderSource:W}}}),vu,xu,Su,xn,Tu,Eu,Sn,ku,Iu,Ec=I(()=>{Tc(),Fr(),Ee(),vu=(e,t,r,i,a,n)=>(e-1)*t+r+(i-1)*a+1-n,xu=(e,t,r,i,a)=>{let n=Math.floor(e/2);t==="SAME_UPPER"?(r[i]=n,r[a]=e-n):t==="SAME_LOWER"&&(r[i]=e-n,r[a]=n)},Su=(e,t,r,i,a,n,s,o,u,l)=>{let d=e.length-2,p=l.length===0;u.length<d&&u.push(...Array(d-u.length).fill(0));let h=e[0],f=t[o?3:1]*a;for(let m=0,w=e.length-d-(o?1:0);m<d;++m,++w){let $=e[w],_=p?$*s[m]:l[m],y=vu($,s[m],n[m],t[w],r[m],_);xu(y,i,n,m,m+d),p&&l.push(s[m]*($-1)+u[m]+(t[w]-1)*r[m]+1-n[m]-n[m+d])}l.splice(0,0,h),l.splice(o?3:1,0,f)},xn=(e,t)=>{let r=e.kernelShape.slice();if(e.kernelShape.length===0||e.kernelShape.reduce((p,h)=>p*h,1)===0){r.length=0;for(let p=2;p<t[1].dims.length;++p)r.push(t[1].dims[p])}let i=e.format==="NHWC";r.splice(0,0,t[1].dims[0]),r.splice(i?3:1,0,t[1].dims[1]);let a=e.pads.slice(),n=e.outputShape.slice(),s=e.outputPadding.slice(),o=t[0].dims,u=e.dilations.slice();if(u.reduce((p,h)=>p+h,0)===0){let p=t[0].dims.length-2;u=new Array(p).fill(1)}let l=e.strides.slice();if(l.reduce((p,h)=>p+h,0)===0){let p=t[0].dims.length-2;l=new Array(p).fill(1)}Su(o,r,u,e.autoPad,e.group,a,l,i,s,n);let d=Object.assign({},e);return Object.assign(d,{kernelShape:r,pads:a,outputPadding:s,outputShape:n,dilations:u,strides:l}),d},Tu=e=>{let t=dn(e),r=e.format,i=["NOTSET","VALID","SAME_UPPER","SAME_LOWER"][typeof e.autoPad>"u"?0:e.autoPad],a=e.dilations,n=e.group??1,s=e.kernelShape,o=e.pads,u=e.strides,l=e.wIsConst(),d=e.outputPadding,p=e.outputShape;return{autoPad:i,format:r,dilations:a,group:n,kernelShape:s,outputPadding:d,outputShape:p,pads:o,strides:u,wIsConst:l,...t,cacheKey:`${e.format};${t.activation};`}},Eu=(e,t)=>{if(!e||e.length!==2&&e.length!==3)throw new Error("Conv requires 2 or 3 inputs");if(e[0].dims.length!==4&&e[0].dims.length!==3)throw new Error("currently only support 2-dimensional conv");if(e[0].dims.length!==e[1].dims.length)throw new Error("filter does not have same dimension as input");let r=e[0].dims[t.format==="NHWC"?e[0].dims.length-1:1],i=e[1].dims[0];if(r!==i)throw new Error("FILTER_IN_CHANNEL should be equal to DATA_CHANNEL");let a=e[1].dims[1]*t.group;if(e.length===3&&(e[2].dims.length!==1||e[2].dims[0]!==a))throw new Error("invalid bias");let n=e[0].dims.length-2;if(t.dilations.reduce((s,o)=>s+o,0)>0&&t.dilations.length!==n)throw new Error(`dilations should be ${n}D`);if(t.strides.reduce((s,o)=>s+o,0)>0&&t.strides.length!==n)throw new Error(`strides should be ${n}D`);if(t.pads.reduce((s,o)=>s+o,0)>0&&t.pads.length!==n*2)throw new Error(`pads should be ${n*2}D`);if(t.outputPadding.length!==n&&t.outputPadding.length!==0)throw new Error(`output_padding should be ${n}D`);if(t.kernelShape.reduce((s,o)=>s+o,0)>0&&t.kernelShape.length!==0&&t.kernelShape.length!==e[1].dims.length-2)throw new Error("invalid kernel shape");if(t.outputShape.length!==0&&t.outputShape.length!==e[0].dims.length-2)throw new Error("invalid output shape")},Sn=(e,t,r,i)=>{let a=e.kernelCustomData.wT??e.compute(We(t[1],[2,3,0,1]),{inputs:[1],outputs:[r.wIsConst?-2:-1]})[0];r.wIsConst&&!e.kernelCustomData.wT&&(e.kernelCustomData.wT=a);let n=[t[0],a];t.length===3&&n.push(t[2]),e.compute($u(n,r,i),{inputs:n})},ku=(e,t)=>{let r=t.format==="NHWC",i=[e.inputs[0].reshape(r?[e.inputs[0].dims[0],1,e.inputs[0].dims[1],e.inputs[0].dims[2]]:[e.inputs[0].dims[0],e.inputs[0].dims[1],1,e.inputs[0].dims[2]]),e.inputs[1].reshape([e.inputs[1].dims[0],e.inputs[1].dims[1],1,e.inputs[1].dims[2]])];e.inputs.length===3&&i.push(e.inputs[2]);let a=t.kernelShape;(a.length===0||a[0]===0)&&(a=[e.inputs[1].dims[2]]);let n=t.dilations;(n.length===0||n[0]===0)&&(n=[1]);let s=t.strides;(s.length===0||s[0]===0)&&(s=[1]);let o=t.pads;o.length===0&&(o=[0,0]),o=[0,o[0],0,o[1]],s=[1].concat(s),n=[1].concat(n),a=[1].concat(a);let u=t.outputPadding;u=[0].concat(u);let l=xn({...t,pads:o,strides:s,dilations:n,kernelShape:a,outputPadding:u},i);Sn(e,i,l,d=>r?[d[0],d[2],d[3]]:[d[0],d[1],d[3]])},Iu=(e,t)=>{if(Eu(e.inputs,t),e.inputs[0].dims.length===3)ku(e,t);else{let r=xn(t,e.inputs);Sn(e,e.inputs,r)}}}),Cu,zu,Au,kc=I(()=>{ue(),oe(),b(),Z(),Cu=(e,t,r,i)=>{let a=M.size(t),n=t.length,s=z("input",e,n),o=q("output",e,n),u=r.dataType===6?r.getInt32Array()[0]:Number(r.getBigInt64Array()[0]),l=M.normalizeAxis(u,n),d=p=>{let h=` i32(${s.indicesGet("inputIndices","uniforms.axis")}) `,f=D("uniforms.input_shape","uniforms.axis",n),m=i.reverse?h+(i.exclusive?" + 1":""):"0",w=i.reverse?f:h+(i.exclusive?"":" + 1");return`
                ${p.registerUniform("outputSize","u32").registerUniform("axis","u32").declareVariables(s,o)}
                ${p.mainStart()}
                  ${p.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}
                  var inputIndices = ${o.offsetToIndices("global_idx")};
                  var sum = ${o.type.value}(0);
                  let first : i32 = ${m};
                  let last : i32 = ${w};
                  for (var i : i32 = first; i < last; i++) {
                    ${s.indicesSet("inputIndices","uniforms.axis","u32(i)")};
                    sum = sum + ${s.getByIndices("inputIndices")};
                  }
                  ${o.setByOffset("global_idx","sum")};
                }`};return{name:"CumSum",shaderCache:{hint:i.cacheKey,inputDependencies:["rank"]},getRunData:()=>({outputs:[{dims:t,dataType:e}],dispatchGroup:{x:Math.ceil(a/64)},programUniforms:[{type:12,data:a},{type:12,data:l},...k(t,t)]}),getShaderSource:d}},zu=(e,t)=>{let r=e.inputs[0].dims,i=e.inputs[0].dataType,a=e.inputs[1];e.compute(Cu(i,r,a,t),{inputs:[0]})},Au=e=>{let t=e.exclusive===1,r=e.reverse===1;return g({exclusive:t,reverse:r})}}),Ou,Ru,Bu,Mu,Du,Ic=I(()=>{ue(),oe(),b(),Z(),Ou=e=>{if(!e||e.length!==1)throw new Error("DepthToSpace requires 1 input.");if(e[0].dims.length!==4)throw new Error("DepthToSpace requires 4D input.")},Ru=(e,t,r,i)=>{let a=[];a.push(`fn perm(i: ${i.type.indices}) -> ${r.type.indices} {
    var a: ${r.type.indices};`);for(let n=0;n<t;++n)a.push(r.indicesSet("a",e[n],`i[${n}]`));return a.push("return a;}"),a.join(`
`)},Bu=(e,t)=>{let r,i,a,n,s,o,u=t.format==="NHWC",l=t.blocksize,d=t.mode==="DCR";u?([r,i,a,n]=e.dims,s=d?[r,i,a,l,l,n/l**2]:[r,i,a,n/l**2,l,l],o=d?[0,1,3,2,4,5]:[0,1,4,2,5,3]):([r,i,a,n]=[e.dims[0],e.dims[2],e.dims[3],e.dims[1]],s=d?[r,l,l,n/l**2,i,a]:[r,n/l**2,l,l,i,a],o=d?[0,3,4,1,5,2]:[0,1,4,2,5,3]);let p=e.reshape(s),h=p.dims.length,f=e.dataType,m=z("a",f,h),w=q("output",f,h),$=_=>`
  ${_.registerUniform("output_size","u32").declareVariables(m,w)}

  ${Ru(o,h,m,w)}

  ${_.mainStart()}
    ${_.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}

    let indices = ${w.offsetToIndices("global_idx")};
    let aIndices = perm(indices);

    ${w.setByOffset("global_idx",m.getByIndices("aIndices"))}
  }`;return{name:"DepthToSpace",shaderCache:{hint:`${e.dims};${t.blocksize};${t.mode}`,inputDependencies:["rank"]},getRunData:_=>{let y=u?[r,i*l,a*l,n/l**2]:[r,n/l**2,i*l,a*l],S=M.size(y),v=p.dims,E=M.sortBasedOnPerm(v,o);return{outputs:[{dims:y,dataType:_[0].dataType}],dispatchGroup:{x:Math.ceil(S/64)},programUniforms:[{type:12,data:S},...k(v,E)]}},getShaderSource:$}},Mu=(e,t)=>{Ou(e.inputs),e.compute(Bu(e.inputs[0],t))},Du=e=>g({blocksize:e.blocksize,mode:e.mode,format:e.format})}),Ra,ia,Tn,Pu,Uu,Nu,Lu,En,Vu,qu,Fu,Cc=I(()=>{ue(),oe(),b(),Z(),Ra="[a-zA-Z]|\\.\\.\\.",ia="("+Ra+")+",Tn="^"+ia+"$",Pu="("+ia+",)*"+ia,Uu="^"+Pu+"$",Nu=class{constructor(e=-1){this.symbolToIndices=new Map,this.inputIndex=e}addSymbol(e,t){let r=this.symbolToIndices.get(e);r===void 0?r=[t]:r.push(t),this.symbolToIndices.set(e,r)}},Lu=class{constructor(e,t){this.equation=t,this.hasEllipsis=!1,this.symbolToInfo=new Map,this.lhs=new Array,this.outputDims=[];let[r,i]=t.includes("->")?t.split("->",2):[t,""];if(!r.match(RegExp(Uu)))throw new Error("Invalid LHS term");if(r.split(",").forEach((a,n)=>{let s=e[n].dims.slice();if(!a.match(RegExp(Tn)))throw new Error("Invalid LHS term");let o=this.processTerm(a,!0,s,n);this.lhs.push(o)}),i==="")i+=[...this.symbolToInfo.entries()].filter(([a,n])=>n.count===1||a==="...").map(([a])=>a).join("");else if(!i.match(RegExp(ia)))throw new Error("Invalid RHS");i.match(RegExp(Ra,"g"))?.forEach(a=>{if(a==="...")this.outputDims=this.outputDims.concat(this.ellipsisDims);else{let n=this.symbolToInfo.get(a);if(n===void 0)throw new Error("Invalid RHS symbol");this.outputDims.push(n.dimValue)}}),this.rhs=this.processTerm(i,!1,this.outputDims)}addSymbol(e,t,r){let i=this.symbolToInfo.get(e);if(i!==void 0){if(i.dimValue!==t&&i.count!==1)throw new Error("Dimension mismatch");i.count++,i.inputIndices.push(r)}else i={count:1,dimValue:t,inputIndices:[r]};this.symbolToInfo.set(e,i)}processTerm(e,t,r,i=-1){let a=r.length,n=!1,s=[],o=0;if(!e.match(RegExp(Tn))&&!t&&e!=="")throw new Error("Invalid LHS term");let u=e.match(RegExp(Ra,"g")),l=new Nu(i);return u?.forEach((d,p)=>{if(d==="..."){if(n)throw new Error("Only one ellipsis is allowed per input term");n=!0;let h=a-u.length+1;if(h<0)throw new Error("Ellipsis out of bounds");if(s=r.slice(o,o+h),this.hasEllipsis){if(this.ellipsisDims.length!==s.length||this.ellipsisDims.toString()!==s.toString())throw new Error("Ellipsis dimensions mismatch")}else if(t)this.hasEllipsis=!0,this.ellipsisDims=s;else throw new Error("Ellipsis must be specified in the LHS");for(let f=0;f<s.length;f++){let m=String.fromCharCode(48+f);l.addSymbol(m,p+f),this.addSymbol(m,r[o++],i)}}else l.addSymbol(d,p+(this.hasEllipsis?this.ellipsisDims.length-1:0)),this.addSymbol(d,r[o++],i)}),l}},En=e=>e+"_max",Vu=(e,t,r,i)=>{let a=e.map(l=>l.length).map((l,d)=>z(`input${d}`,t,l)),n=M.size(i),s=q("output",t,i.length),o=[...r.symbolToInfo.keys()].filter(l=>!r.rhs.symbolToIndices.has(l)),u=l=>{let d=[],p="var prod = 1.0;",h="var sum = 0.0;",f="sum += prod;",m=[],w=[],$=[],_=[],y=r.symbolToInfo.size===r.rhs.symbolToIndices.size;r.symbolToInfo.forEach((v,E)=>{if(r.rhs.symbolToIndices.has(E)){let B=r.rhs.symbolToIndices.get(E)?.[0];B!==void 0&&r.lhs.forEach((R,U)=>{if(v.inputIndices.includes(U)){let W=R.symbolToIndices.get(E);if(W===void 0)throw new Error("Invalid symbol error");W.forEach(X=>{d.push(`${a[U].indicesSet(`input${U}Indices`,X,s.indicesGet("outputIndices",B))}`)})}})}else r.lhs.forEach((B,R)=>{if(v.inputIndices.includes(R)){let U=B.symbolToIndices.get(E);if(U===void 0)throw new Error("Invalid symbol error");U.forEach(W=>{m.push(`${a[R].indicesSet(`input${R}Indices`,W,`${E}`)}`)}),_.push(`prod *= ${a[R].getByIndices(`input${R}Indices`)};`)}}),w.push(`for(var ${E}: u32 = 0; ${E} < uniforms.${En(E)}; ${E}++) {`),$.push("}")});let S=y?[...d,`let sum = ${a.map((v,E)=>v.getByIndices(`input${E}Indices`)).join(" * ")};`]:[...d,h,...w,...m,p,..._,f,...$];return`
            ${l.registerUniforms(o.map(v=>({name:`${En(v)}`,type:"u32"}))).registerUniform("outputSize","u32").declareVariables(...a,s)}

            ${l.mainStart()}
            ${l.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}
            var outputIndices = ${s.offsetToIndices("global_idx")};
            ${a.map((v,E)=>`var input${E}Indices: ${a[E].type.indices};`).join(`
`)}
            ${S.join(`
`)};
            ${s.setByOffset("global_idx","sum")};
          }`};return{name:"Einsum",shaderCache:{hint:r.equation,inputDependencies:e.map(()=>"rank")},getRunData:()=>{let l=o.filter(p=>r.symbolToInfo.has(p)).map(p=>({type:12,data:r.symbolToInfo.get(p)?.dimValue||0}));l.push({type:12,data:n});let d=e.map((p,h)=>[...k(p)]).reduce((p,h)=>p.concat(h),l);return d.push(...k(i)),{outputs:[{dims:i,dataType:t}],dispatchGroup:{x:Math.ceil(n/64)},programUniforms:d}},getShaderSource:u}},qu=(e,t)=>{let r=new Lu(e.inputs,t.equation),i=r.outputDims,a=e.inputs.map((n,s)=>n.dims);e.compute(Vu(a,e.inputs[0].dataType,r,i))},Fu=e=>{let t=e.equation.replace(/\s+/g,"");return g({equation:t})}}),Wu,kn,Gu,ju,Hu,zc=I(()=>{ue(),oe(),Z(),Wu=e=>{if(!e||e.length!==2)throw new Error("Expand requires 2 input.");let t=e[0].dims,r=Array.from(e[1].getBigInt64Array(),Number),i=r.length<t.length?0:r.length-t.length,a=t.length<r.length?0:t.length-r.length;for(;i<r.length&&a<t.length;++i,++a)if(r[i]!==t[a]&&r[i]!==1&&t[a]!==1)throw new Error("Expand requires shape to be broadcastable to input")},kn=(e,t)=>{let r=e.length-t.length,i=[];for(let a=0;a<r;++a)i.push(e[a]);for(let a=0;a<t.length;++a)i.push(t[a]===1?e[a+r]:t[a]);return i},Gu=(e,t)=>e.length>t.length?kn(e,t):kn(t,e),ju=e=>{let t=e[0].dims,r=Array.from(e[1].getBigInt64Array(),Number),i=Gu(t,r),a=e[0].dataType,n=a===9||M.size(t)===1,s=a===9||t.length>0&&t[t.length-1]%4===0?4:1,o=n||i.length>0&&i[i.length-1]%4===0?4:1,u=Math.ceil(M.size(i)/o),l=p=>{let h=z("input",a,t.length,s),f=q("output",a,i.length,o),m;if(a===9){let w=($,_,y="")=>`
          let outputIndices${_} = ${f.offsetToIndices(`outputOffset + ${_}u`)};
          let offset${_} = ${h.broadcastedIndicesToOffset(`outputIndices${_}`,f)};
          let index${_} = offset${_} / 4u;
          let component${_} = offset${_} % 4u;
          ${$}[${_}] = ${y}(${h.getByOffset(`index${_}`)}[component${_}]);
        `;m=`
        let outputOffset = global_idx * ${o};
        var data = vec4<u32>(0);
        ${w("data",0,"u32")}
        ${w("data",1,"u32")}
        ${w("data",2,"u32")}
        ${w("data",3,"u32")}
        ${f.setByOffset("global_idx","data")}
      }`}else m=`
        let outputIndices = ${f.offsetToIndices(`global_idx * ${o}`)};
        let inputOffset = ${h.broadcastedIndicesToOffset("outputIndices",f)};
        let data = ${f.type.value}(${h.getByOffset(`inputOffset / ${s}`)});
        ${f.setByOffset("global_idx","data")}
      }`;return`
    ${p.registerUniform("vec_size","u32").declareVariables(h,f)}
    ${p.mainStart()}
    ${p.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.vec_size")}
    ${m}`},d=[{type:12,data:u},...k(t,i)];return{name:"Expand",shaderCache:{hint:`${i.length};${s}${o}`,inputDependencies:["rank"]},getShaderSource:l,getRunData:()=>({outputs:[{dims:i,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(u/64)},programUniforms:d})}},Hu=e=>{Wu(e.inputs),e.compute(ju(e.inputs),{inputs:[0]})}}),Ku,Zu,Ac=I(()=>{ue(),oe(),Z(),ln(),Ku=e=>{let t=e[0].dataType,r=M.size(e[0].dims),i=M.size(e[1].dims),a=i%4===0,n=s=>{let o=z("x",t,[1],4),u=z("bias",t,[1],4),l=q("y",t,[1],4),d=[{name:"output_vec_size",type:"u32"},{name:"bias_size",type:"u32"}],p=f=>`
      let bias${f}_offset: u32 = (global_idx * 4 + ${f}) % uniforms.bias_size;
      let bias${f} = ${u.getByOffset(`bias${f}_offset / 4`)}[bias${f}_offset % 4];`,h=a?`
      let bias = ${u.getByOffset("global_idx % (uniforms.bias_size / 4)")};`:`${p(0)}${p(1)}${p(2)}${p(3)}
      let bias = ${o.type.value}(bias0, bias1, bias2, bias3);`;return`${s.registerUniforms(d).declareVariables(o,u,l)}

    ${on(C(t))}

    ${s.mainStart(T)}
      ${s.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_vec_size")}

      let x = ${o.getByOffset("global_idx")};
      ${h}
      let x_in = x + bias;
      ${l.setByOffset("global_idx",un("x_in"))}
    }`};return{name:"FastGeluWithBias",shaderCache:{hint:`${a}`,inputDependencies:["type","type"]},getShaderSource:n,getRunData:s=>({outputs:[{dims:s[0].dims,dataType:s[0].dataType}],programUniforms:[{type:12,data:Math.ceil(r/4)},{type:12,data:i}],dispatchGroup:{x:Math.ceil(r/T/4)}})}},Zu=e=>{e.inputs.length<2||M.size(e.inputs[1].dims)===0?Co(e):e.compute(Ku(e.inputs))}}),Qu,Xu,Yu,Ju,Oc=I(()=>{ue(),oe(),b(),Z(),Qu=e=>{if(!e||e.length!==2)throw new Error("Gather requires 2 inputs.")},Xu=(e,t)=>{let r=e[0].dims,i=e[1].dims,a=r.length,n=M.normalizeAxis(t.axis,a),s=r.slice(0);s.splice(n,1,...i);let o=r[n],u=e[0].dataType===9?4:1,l=Math.ceil(M.size(s)/u),d=[{type:12,data:l},{type:6,data:o},{type:12,data:n},...k(e[0].dims,e[1].dims,s)],p=h=>{let f=z("data",e[0].dataType,e[0].dims.length,u),m=z("inputIndices",e[1].dataType,e[1].dims.length),w=q("output",e[0].dataType,s.length,u),$=y=>{let S=i.length,v=`var indicesIndices${y}  = ${m.type.indices}(0);`;for(let E=0;E<S;E++)v+=`${S>1?`indicesIndices${y}[${E}]`:`indicesIndices${y}`} = ${s.length>1?`outputIndices${y}[uniforms.axis + ${E}]`:`outputIndices${y}`};`;v+=`
          var idx${y} = ${m.getByIndices(`indicesIndices${y}`)};
          if (idx${y} < 0) {
            idx${y} = idx${y} + uniforms.axisDimLimit;
          }
          var dataIndices${y} : ${f.type.indices};
        `;for(let E=0,B=0;E<a;E++)E===n?(v+=`${a>1?`dataIndices${y}[${E}]`:`dataIndices${y}`} = u32(idx${y});`,B+=S):(v+=`${a>1?`dataIndices${y}[${E}]`:`dataIndices${y}`} = ${s.length>1?`outputIndices${y}[${B}]`:`outputIndices${y}`};`,B++);return v},_;if(e[0].dataType===9){let y=(S,v,E="")=>`
          let outputIndices${v} = ${w.offsetToIndices(`outputOffset + ${v}u`)};
          ${$(v)};
          let offset${v} = ${f.indicesToOffset(`dataIndices${v}`)};
          let index${v} = offset${v} / 4u;
          let component${v} = offset${v} % 4u;
          ${S}[${v}] = ${E}(${f.getByOffset(`index${v}`)}[component${v}]);
        `;_=`
        let outputOffset = global_idx * ${u};
        var value = vec4<u32>(0);
        ${y("value",0,"u32")}
        ${y("value",1,"u32")}
        ${y("value",2,"u32")}
        ${y("value",3,"u32")}
        ${w.setByOffset("global_idx","value")}
      `}else _=`
      let outputIndices = ${w.offsetToIndices("global_idx")};
      ${$("")};
      let value = ${f.getByIndices("dataIndices")};
      ${w.setByOffset("global_idx","value")};
      `;return`
      ${h.registerUniform("outputSize","u32").registerUniform("axisDimLimit","i32").registerUniform("axis","u32").declareVariables(f,m,w)}
      ${h.mainStart()}
        ${h.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}
        ${_}
      }`};return{name:"Gather",shaderCache:{hint:t.cacheKey,inputDependencies:["rank","rank"]},getRunData:()=>({outputs:[{dims:s,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(l/64)},programUniforms:d}),getShaderSource:p}},Yu=e=>g({axis:e.axis}),Ju=(e,t)=>{let r=e.inputs;Qu(r),e.compute(Xu(e.inputs,t))}}),el,tl,rl,Rc=I(()=>{ue(),oe(),Z(),el=(e,t,r,i,a,n,s,o,u)=>{let l=[{type:12,data:n},{type:12,data:i},{type:12,data:a},{type:12,data:r},{type:12,data:s},{type:12,data:o},{type:12,data:u}],d=[n];l.push(...k(t.dims,d));let p=h=>{let f=z("indices_data",t.dataType,t.dims.length),m=q("input_slice_offsets_data",12,1,1),w=[f,m],$=[{name:"output_size",type:"u32"},{name:"batch_dims",type:"u32"},{name:"input_dims",type:"u32",length:a.length},{name:"sizes_from_slice_dims_data",type:"u32",length:r.length},{name:"num_slices_per_batch",type:"u32"},{name:"input_batch_stride",type:"u32"},{name:"num_slice_dims",type:"u32"}];return`
  ${h.registerUniforms($).declareVariables(...w)}
  ${h.mainStart()}
    ${h.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
    let batch_idx = global_idx / uniforms.num_slices_per_batch;
    let base_offset = batch_idx * uniforms.input_batch_stride;

    let slice_indices_base_offset = global_idx * uniforms.num_slice_dims;
    var relative_slice_offset = 0;
    for (var dim_idx = 0u; dim_idx < uniforms.num_slice_dims; dim_idx ++) {
      var index = i32(indices_data[dim_idx + slice_indices_base_offset].x);
      let input_dim_idx = uniforms.batch_dims + dim_idx;
      if (index < 0) {
        ${a.length===1?"index += i32(uniforms.input_dims);":"index += i32(uniforms.input_dims[input_dim_idx]);"}
      }
      ${r.length===1?"relative_slice_offset += index * i32(uniforms.sizes_from_slice_dims_data);":"relative_slice_offset += index * i32(uniforms.sizes_from_slice_dims_data[dim_idx]);"}
    }

    input_slice_offsets_data[global_idx] =  base_offset + u32(relative_slice_offset);
  }`};return e.compute({name:"computeSliceOffsets",shaderCache:{hint:`${a.length}_${r.length}`,inputDependencies:["rank"]},getRunData:()=>({outputs:[{dims:d,dataType:e.inputs[1].dataType}],dispatchGroup:{x:Math.ceil(n/64)},programUniforms:l}),getShaderSource:p},{inputs:[t],outputs:[-1]})[0]},tl=(e,t)=>{let r=e.inputs,i=r[0].dims,a=r[0].dataType,n=r[1].dims,s=n[n.length-1],o=M.sizeToDimension(n,n.length-1),u=M.sizeFromDimension(i,t.batchDims+s),l=M.sizeToDimension(i,t.batchDims),d=M.sizeFromDimension(i,t.batchDims),p=o/l,h=new Array(s),f=u;for(let v=0;v<s;++v)h[s-1-v]=f,f*=i[t.batchDims+s-1-v];let m=el(e,r[1],h,t.batchDims,i,o,p,d,s),w=t.batchDims+s;if(w>i.length)throw new Error("last dimension of indices must not be larger than rank of input tensor");let $=n.slice(0,-1).concat(i.slice(w)),_=M.size($),y=[{type:12,data:_},{type:12,data:u},...k(r[0].dims,m.dims,$)],S=v=>{let E=z("data",r[0].dataType,r[0].dims.length),B=z("slice_offsets",12,m.dims.length),R=q("output",r[0].dataType,$.length);return`
          ${v.registerUniform("output_size","u32").registerUniform("slice_size","u32").declareVariables(E,B,R)}
            ${v.mainStart()}
            ${v.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
          let slice_offset = slice_offsets[global_idx / uniforms.slice_size];
          output[global_idx] = data[u32(slice_offset) + global_idx % uniforms.slice_size];
        }`};e.compute({name:"GatherND",shaderCache:{hint:t.cacheKey,inputDependencies:["rank","rank"]},getRunData:()=>({outputs:[{dims:$,dataType:a}],dispatchGroup:{x:Math.ceil(_/64)},programUniforms:y}),getShaderSource:S},{inputs:[r[0],m]})},rl=e=>({batchDims:e.batch_dims,cacheKey:""})}),il,al,nl,sl,Bc=I(()=>{ue(),oe(),b(),Z(),il=(e,t)=>{if(e.length<3||e.length>4)throw new Error("GatherBlockQuantized requires 3 or 4 inputs.");let r=M.normalizeAxis(t.quantizeAxis,e[0].dims.length),i=t.blockSize,a=e[0],n=e[2],s=e.length===4?e[3]:void 0;if(n.dims.length!==a.dims.length||!a.dims.map((o,u)=>u===r?Math.ceil(o/i)===n.dims[u]:o===n.dims[u]).reduce((o,u)=>o&&u,!0))throw new Error("Scales must have the same rank as the input tensor and the dims should match except on gatherAxis.");if(s){if(s.dataType!==a.dataType)throw new Error("Zero point must have the same data type as the input tensor.");if(s.dims.length!==n.dims.length||!s.dims.map((o,u)=>o===n.dims[u]).reduce((o,u)=>o&&u,!0))throw new Error("Zero point must have the same rank as the input tensor and the dims should match except on quantizeAxis.")}},al=(e,t)=>{let r=e[0].dims,i=e[1].dims,a=r.length,n=M.normalizeAxis(t.gatherAxis,a),s=M.normalizeAxis(t.quantizeAxis,a),o=r.slice(0);o.splice(n,1,...i);let u=M.size(o),l=e[2].dataType,d=e[0].dataType===22,p=[{type:12,data:u},{type:12,data:s},{type:12,data:n},{type:12,data:t.blockSize},...k(...e.map((f,m)=>f.dims),o)],h=f=>{let m=z("data",e[0].dataType,e[0].dims.length),w=z("inputIndices",e[1].dataType,e[1].dims.length),$=z("scales",e[2].dataType,e[2].dims.length),_=e.length>3?z("zeroPoint",e[3].dataType,e[3].dims.length):void 0,y=q("output",l,o.length),S=[m,w,$];_&&S.push(_);let v=[{name:"output_size",type:"u32"},{name:"quantize_axis",type:"u32"},{name:"gather_axis",type:"u32"},{name:"block_size",type:"u32"}];return`
        ${f.registerUniforms(v).declareVariables(...S,y)}
        ${f.mainStart()}
        let output_indices = ${y.offsetToIndices("global_idx")};
        var indices_indices = ${w.type.indices}(0);
        ${i.length>1?`
          for (var i: u32 = 0; i < ${i.length}; i++) {
            let index = ${y.indicesGet("output_indices","uniforms.gather_axis + i")};
            ${w.indicesSet("indices_indices","i","index")};
          }`:`indices_indices = ${y.indicesGet("output_indices","uniforms.gather_axis")};`};
        var data_indices = ${m.type.indices}(0);
        for (var i: u32 = 0; i < uniforms.gather_axis; i++) {
          let index = ${y.indicesGet("output_indices","i")};
          ${m.indicesSet("data_indices","i","index")};
        }
        var index_from_indices = ${w.getByIndices("indices_indices")};
        if (index_from_indices < 0) {
          index_from_indices += ${r[n]};
        }
        ${m.indicesSet("data_indices","uniforms.gather_axis","u32(index_from_indices)")};
        for (var i = uniforms.gather_axis + 1; i < ${o.length}; i++) {
          let index = ${y.indicesGet("output_indices",`i + ${i.length} - 1`)};
          ${m.indicesSet("data_indices","i","index")};
        }
        let data_offset = ${m.indicesToOffset("data_indices")};
        let data_index = data_offset % 8;
        // Convert 4-bit packed data to 8-bit packed data.
        let packed_4bit_quantized_data = ${m.getByOffset("data_offset / 8")};
        let packed_8bit_quantized_data = (packed_4bit_quantized_data >> (4 * (data_index % 2))) & 0x0f0f0f0f;
        let quantized_data_vec = ${d?"unpack4xI8":"unpack4xU8"}(u32(packed_8bit_quantized_data));
        let quantized_data = quantized_data_vec[data_index / 2];
        var scale_indices = data_indices;
        let quantize_axis_index = ${$.indicesGet("data_indices","uniforms.quantize_axis")} / uniforms.block_size;
        ${$.indicesSet("scale_indices","uniforms.quantize_axis","quantize_axis_index")};
        var scale = ${$.getByIndices("scale_indices")};
        ${_?`
              let zero_point_indices = scale_indices;
              let zero_point_offset = ${_.indicesToOffset("zero_point_indices")};
              let zero_point_index = zero_point_offset % 8;
              let packed_4bit_zero_points = ${_.getByOffset("zero_point_offset / 8")};
              let packed_8bit_zero_points = (packed_4bit_zero_points >> (4 * (zero_point_index % 2))) & 0x0f0f0f0f;
              let zero_point_vec = ${d?"unpack4xI8":"unpack4xU8"}(u32(packed_8bit_zero_points));
              let zero_point = zero_point_vec[zero_point_index / 2];`:"var zero_point = 0"};
        let dequantized_data = ${C(l)}(quantized_data - zero_point) * scale;
        ${y.setByOffset("global_idx","dequantized_data")};
    }`};return{name:"GatherBlockQuantized",shaderCache:{hint:`${t.cacheKey};${e.filter((f,m)=>m!==1).map(f=>f.dims.join("_")).join(";")}`,inputDependencies:Array.from({length:e.length},(f,m)=>"rank")},getRunData:()=>({outputs:[{dims:o,dataType:l}],dispatchGroup:{x:Math.ceil(u/64)},programUniforms:p}),getShaderSource:h}},nl=(e,t)=>{let r=e.inputs;il(r,t),e.compute(al(e.inputs,t))},sl=e=>g({blockSize:e.blockSize,gatherAxis:e.gatherAxis,quantizeAxis:e.quantizeAxis})}),ol,ul,ll,dl,Mc=I(()=>{ue(),oe(),b(),Z(),ol=e=>{if(!e||e.length!==2)throw new Error("GatherElements requires 2 inputs.");if(e[0].dims.length<1)throw new Error("GatherElements requires that the data input be rank >= 1.");if(e[0].dims.length!==e[1].dims.length)throw new Error(`GatherElements requires that the data input and
                     indices input tensors be of same rank.`)},ul=(e,t)=>{let r=e[0].dims,i=e[0].dataType,a=r.length,n=e[1].dims,s=e[1].dataType,o=M.normalizeAxis(t.axis,a),u=r[o],l=n.slice(0),d=M.size(l),p=z("input",i,a),h=z("indicesInput",s,n.length),f=q("output",i,l.length),m=[{type:12,data:d},{type:6,data:u},{type:12,data:o}];return m.push(...k(r,n,l)),{name:"GatherElements",shaderCache:{inputDependencies:["rank","rank"]},getRunData:()=>({outputs:[{dims:l,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(d/64)},programUniforms:m}),getShaderSource:w=>`
      ${w.registerUniform("outputSize","u32").registerUniform("axisDimLimit","i32").registerUniform("axis","u32").declareVariables(p,h,f)}
      ${w.mainStart()}
      ${w.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}

      let outputIndices = ${f.offsetToIndices("global_idx")};

      var idx = ${h.getByOffset("global_idx")};
      if (idx < 0) {
        idx = idx + uniforms.axisDimLimit;
      }
      var inputIndices = ${p.type.indices}(outputIndices);
      ${p.indicesSet("inputIndices","uniforms.axis","u32(idx)")};
      let value = ${p.getByIndices("inputIndices")};

      ${f.setByOffset("global_idx","value")};
  }`}},ll=e=>g({axis:e.axis}),dl=(e,t)=>{let r=e.inputs;ol(r),e.compute(ul(e.inputs,t))}}),pl,cl,hl,fl,Dc=I(()=>{ue(),oe(),Z(),pl=e=>{if(!e)throw new Error("Input is missing");if(e.length<2||e.length>3)throw new Error("Invaid input number.");if(e.length===3&&e[2].dims.length>2)throw new Error("Invalid input shape of C");if(e[0].dataType!==e[1].dataType||e.length===3&&e[0].dataType!==e[2].dataType)throw new Error("Input types are mismatched")},cl=(e,t)=>{let r=e[0].dims.slice(),i=e[1].dims.slice(),[a,n,s]=ri.getShapeOfGemmResult(r,t.transA,i,t.transB,e.length===3?e[2].dims:void 0),o=[a,n];if(!o)throw new Error("Can't use gemm on the given tensors");let u=16,l=Math.ceil(n/u),d=Math.ceil(a/u);M.size(o);let p=[{type:12,data:l},{type:12,data:a},{type:12,data:n},{type:12,data:s},{type:1,data:t.alpha},{type:1,data:t.beta}],h=["type","type"];e.length===3&&(p.push(...k(e[2].dims)),h.push("rank")),p.push(...k(o));let f=m=>{let w=z("a",e[0].dataType,e[0].dims),$=z("b",e[1].dataType,e[1].dims),_=null,y=[w,$];e.length===3&&(_=z("c",e[2].dataType,e[2].dims.length),y.push(_));let S=q("output",e[0].dataType,o.length);y.push(S);let v=[{name:"num_tile_n",type:"u32"},{name:"M",type:"u32"},{name:"N",type:"u32"},{name:"K",type:"u32"},{name:"alpha",type:"f32"},{name:"beta",type:"f32"}],E="",B="";t.transA&&t.transB?(B=`
      var col = tile_row_start + local_id.x;
      var row = k_start + local_id.y;
      if (col < uniforms.M && row < uniforms.K) {
        tile_a[local_id.y][local_id.x] = a[row * uniforms.M + col];
      } else {
        tile_a[local_id.y][local_id.x] = ${w.type.value}(0);
      }

      col = k_start + local_id.x;
      row = tile_col_start + local_id.y;
      if (col < uniforms.K && row < uniforms.N) {
        tile_b[local_id.y][local_id.x] = b[row * uniforms.K + col];
      } else {
        tile_b[local_id.y][local_id.x] = ${$.type.value}(0);
      }
      `,E="value += tile_a[k][local_id.y] * tile_b[local_id.x][k];"):t.transA&&!t.transB?(B=`
      var col = tile_row_start + local_id.x;
      var row = k_start + local_id.y;
      if (col < uniforms.M && row < uniforms.K) {
        tile_a[local_id.y][local_id.x] = a[row * uniforms.M + col];
      } else {
        tile_a[local_id.y][local_id.x] = ${w.type.value}(0);
      }

      col = tile_col_start + local_id.x;
      row = k_start + local_id.y;
      if (col < uniforms.N && row < uniforms.K) {
        tile_b[local_id.y][local_id.x] = b[row * uniforms.N + col];
      } else {
        tile_b[local_id.y][local_id.x] = ${$.type.value}(0);
      }
      `,E="value += tile_a[k][local_id.y] * tile_b[k][local_id.x];"):!t.transA&&t.transB?(B=`
      var col = k_start + local_id.x;
      var row = tile_row_start + local_id.y;
      if (col < uniforms.K && row < uniforms.M) {
        tile_a[local_id.y][local_id.x] = a[row * uniforms.K + col];
      } else {
        tile_a[local_id.y][local_id.x] = ${w.type.value}(0);
      }

      col = k_start + local_id.x;
      row = tile_col_start + local_id.y;
      if (col < uniforms.K && row < uniforms.N) {
        tile_b[local_id.y][local_id.x] = b[row * uniforms.K + col];
      } else {
        tile_b[local_id.y][local_id.x] = ${$.type.value}(0);
      }
      `,E="value += tile_a[local_id.y][k] * tile_b[local_id.x][k];"):!t.transA&&!t.transB&&(B=`
      var col = k_start + local_id.x;
      var row = tile_row_start + local_id.y;
      if (col < uniforms.K && row < uniforms.M) {
        tile_a[local_id.y][local_id.x] = a[row * uniforms.K + col];
      } else {
        tile_a[local_id.y][local_id.x] = ${w.type.value}(0);
      }

      col = tile_col_start + local_id.x;
      row = k_start + local_id.y;
      if (col < uniforms.N && row < uniforms.K) {
        tile_b[local_id.y][local_id.x] = b[row * uniforms.N + col];
      } else {
        tile_b[local_id.y][local_id.x] = ${$.type.value}(0);
      }
      `,E="value += tile_a[local_id.y][k] * tile_b[k][local_id.x];");let R=t.alpha===1?"":"value *= uniforms.alpha;";return`
  ${m.registerUniforms(v).declareVariables(...y)}
  var<workgroup> tile_a: array<array<${w.type.storage}, ${u}>, ${u}>;
  var<workgroup> tile_b: array<array<${$.type.storage}, ${u}>, ${u}>;
  ${m.mainStart([u,u,1])}
    let tile_col_start = (workgroup_index % uniforms.num_tile_n) * ${u};
    let tile_row_start = (workgroup_index / uniforms.num_tile_n) * ${u};
    let num_tiles = (uniforms.K - 1) / ${u} + 1;
    var k_start = 0u;
    var value = ${S.type.value}(0);
    for (var t: u32 = 0u; t < num_tiles; t++) {
      ${B}
      k_start = k_start + ${u};
      workgroupBarrier();

      for (var k: u32 = 0u; k < ${u}; k++) {
        ${E}
      }
      workgroupBarrier();
    }

    ${R}
    let m = tile_row_start + local_id.y;
    let n = tile_col_start + local_id.x;
    ${_!=null?`let cOffset = ${_.broadcastedIndicesToOffset("vec2(m, n)",S)}; value += ${S.type.value}(uniforms.beta) * ${_.getByOffset("cOffset")};`:""}
    if (m < uniforms.M && n < uniforms.N) {
      output[m * uniforms.N + n] = value;
    }
  }`};return{name:"GemmShared",shaderCache:{hint:`${t.cacheKey}`,inputDependencies:h},getRunData:()=>({outputs:[{dims:o,dataType:e[0].dataType}],dispatchGroup:{x:l*d},programUniforms:p}),getShaderSource:f}},hl=e=>{let t=e.transA,r=e.transB,i=e.alpha,a=e.beta;return{transA:t,transB:r,alpha:i,beta:a,cacheKey:`${e.transA};${e.transB};${e.alpha===1}`}},fl=(e,t)=>{pl(e.inputs),e.compute(cl(e.inputs,t))}}),Wt,Xt,Wr,Gr,ml,gl,yl,wl,_l,bl,$l,vl,xl,Sl,Pc=I(()=>{ue(),oe(),b(),Z(),[Wt,Xt,Wr,Gr]=[0,1,2,3],ml=e=>{if(e[0].dims.length!==4)throw new Error("only 4-D tensor is supported.");if(e[0].dims.length!==e[1].dims.length)throw new Error("input dimensions must be equal to grid dimensions");if(e[0].dims.length-2!==e[1].dims[e[1].dims.length-1])throw new Error(`last dimension of grid must be equal to ${e[0].dims.length-2}`);if(e[0].dims[0]!==e[1].dims[0])throw new Error("grid batch size must match input batch size")},gl=`
  fn gs_get_cubic_coeffs(x: f32) -> vec4<f32> {
    let cubic_alpha = -0.75f;
    let x_abs = abs(x);
    var coeffs: vec4<f32>;
    coeffs[0] = (((cubic_alpha * (x_abs + 1) - 5 * cubic_alpha) * (x_abs + 1) + 8 * cubic_alpha) * (x_abs + 1) - 4 * cubic_alpha);
    coeffs[1] = (((cubic_alpha + 2) * x_abs - (cubic_alpha + 3)) * x_abs * x_abs + 1);
    coeffs[2] = (((cubic_alpha + 2) * (1 - x_abs) - (cubic_alpha + 3)) * (1 - x_abs) * (1 - x_abs) + 1);
    coeffs[3] = (((cubic_alpha * (2 - x_abs) - 5 * cubic_alpha) * (2 - x_abs) + 8 * cubic_alpha) * (2 - x_abs) - 4 * cubic_alpha);
    return coeffs;
  }
`,yl=e=>`
  fn gs_bicubic_interpolate(p: mat4x4<${e}>, x: f32, y: f32) -> ${e} {
    var v: vec4<f32>;
    var coeffs = gs_get_cubic_coeffs(x);
    for (var i = 0; i < 4; i++) {
      v[i] = coeffs[0] * p[i][0] + coeffs[1] * p[i][1] + coeffs[2] * p[i][2] + coeffs[3] * p[i][3];
    }
    coeffs = gs_get_cubic_coeffs(y);
    let pixel = ${e}(coeffs[0] * v[0] + coeffs[1] * v[1] + coeffs[2] * v[2] + coeffs[3] * v[3]);
    return pixel;
  }
`,wl=e=>`
  fn gs_denormalize(n: f32, length: i32) -> f32 {
    ${e.alignCorners===0?`
    // alignCorners: false => [-1, 1] to [-0.5, length - 0.5]
    return ((n + 1.0) * f32(length) - 1.0) / 2.0;
    `:`
    // alignCorners: true => [-1, 1] to [0, length - 1]
    return (n + 1.0) / 2.0 * (f32(length - 1));
    `}
  }
`,_l=e=>`
  ${e.paddingMode==="reflection"?`
      fn gs_reflect(x: i32, x_min: f32, x_max: f32) -> u32 {
        var dx = 0.0;
        var fx = f32(x);
        let range = x_max - x_min;
        if (fx < x_min) {
          dx = x_min - fx;
          let n = u32(dx / range);
          let r = dx - f32(n) * range;
          if (n % 2 == 0) {
            fx = x_min + r;
          } else {
            fx = x_max - r;
          }
        } else if (fx > x_max) {
          dx = fx - x_max;
          let n = u32(dx / range);
          let r = dx - f32(n) * range;
          if (n % 2 == 0) {
            fx = x_max - r;
          } else {
            fx = x_min + r;
          }
        }
        return u32(fx);
      }`:""}
`,bl=(e,t,r)=>`
  fn pixel_at_grid(r: i32, c: i32, H: i32, W: i32, batch: u32, channel: u32, border: vec4<f32>) -> ${t} {
     var pixel = ${t}(0);
     var indices = vec4<u32>(0);
     indices[${Wt}] = batch;
     indices[${Xt}] = channel;`+(()=>{switch(r.paddingMode){case"zeros":return`
          if (r >= 0 && r < H && c >=0 && c < W) {
            indices[${Wr}] = u32(r);
            indices[${Gr}] = u32(c);
          } else {
            return ${t}(0);
          }
        `;case"border":return`
          indices[${Wr}] = u32(clamp(r, 0, H - 1));
          indices[${Gr}] = u32(clamp(c, 0, W - 1));
        `;case"reflection":return`
          indices[${Wr}] = gs_reflect(r, border[1], border[3]);
          indices[${Gr}] = gs_reflect(c, border[0], border[2]);
        `;default:throw new Error(`padding mode ${r.paddingMode} is not supported`)}})()+`
    return ${e.getByIndices("indices")};
  }
`,$l=(e,t,r)=>(()=>{switch(r.mode){case"nearest":return`
          let result = pixel_at_grid(i32(round(y)), i32(round(x)), H_in, W_in, indices[${Wt}], indices[${Xt}], border);
        `;case"bilinear":return`
          let x1 = i32(floor(x));
          let y1 = i32(floor(y));
          let x2 = x1 + 1;
          let y2 = y1 + 1;

          let p11 = pixel_at_grid(y1, x1, H_in, W_in, indices[${Wt}], indices[${Xt}], border);
          let p12 = pixel_at_grid(y1, x2, H_in, W_in, indices[${Wt}], indices[${Xt}], border);
          let p21 = pixel_at_grid(y2, x1, H_in, W_in, indices[${Wt}], indices[${Xt}], border);
          let p22 = pixel_at_grid(y2, x2, H_in, W_in, indices[${Wt}], indices[${Xt}], border);

          let dx2 = ${t}(f32(x2) - x);
          let dx1 = ${t}(x - f32(x1));
          let dy2 = ${t}(f32(y2) - y);
          let dy1 = ${t}(y - f32(y1));
          let result = dy2 * (dx2 * p11 + dx1 * p12) + dy1 * (dx2 * p21 + dx1 * p22);
        `;case"bicubic":return`
          let x0 = i32(floor(x)) - 1;
          let y0 = i32(floor(y)) - 1;
          var p: mat4x4<${t}>;
          for (var h = 0; h < 4; h++) {
            for (var w = 0; w < 4; w++) {
              p[h][w] = pixel_at_grid(h + y0, w + x0, H_in, W_in, indices[${Wt}], indices[${Xt}], border);
            }
          }

          let dx = x - f32(x0 + 1);
          let dy = y - f32(y0 + 1);
          let result = gs_bicubic_interpolate(p, dx, dy);
        `;default:throw new Error(`mode ${r.mode} is not supported`)}})()+`${e.setByOffset("global_idx","result")}`,vl=(e,t)=>{let r=z("x",e[0].dataType,e[0].dims.length),i=[e[1].dims[0],e[1].dims[1],e[1].dims[2]],a=z("grid",e[1].dataType,i.length,2),n=[e[0].dims[0],e[0].dims[1],e[1].dims[1],e[1].dims[2]];t.format==="NHWC"&&(n=[e[0].dims[0],e[1].dims[1],e[1].dims[2],e[0].dims[3]],[Wt,Xt,Wr,Gr]=[0,3,1,2]);let s=q("output",e[0].dataType,n.length),o=r.type.value,u=M.size(n),l=[{type:12,data:u},...k(e[0].dims,i,n)],d=p=>`
  ${p.registerUniform("output_size","u32").declareVariables(r,a,s)}
  ${gl}
  ${yl(o)}
  ${wl(t)}
  ${_l(t)}
  ${bl(r,o,t)}

  ${p.mainStart()}
    ${p.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
      let H_in = i32(uniforms.x_shape[${Wr}]);
      let W_in = i32(uniforms.x_shape[${Gr}]);

      ${t.alignCorners===0?`
      let x_min = -0.5;
      let x_max = f32(W_in) - 0.5;
      let y_min = -0.5;
      let y_max = f32(H_in) - 0.5;
      `:`
      let x_min = 0.0;
      let x_max = f32(W_in) - 1.0;
      let y_min = 0.0;
      let y_max = f32(H_in) - 1.0;
      `};
      let border = vec4<f32>(x_min, y_min, x_max, y_max);

      let indices = ${s.offsetToIndices("global_idx")};
      var grid_indices = vec3<u32>(indices[${Wt}], indices[${Wr}], indices[${Gr}]);
      let nxy = ${a.getByIndices("grid_indices")};
      var x = gs_denormalize(f32(nxy[0]), W_in);
      var y = gs_denormalize(f32(nxy[1]), H_in);

      ${$l(s,o,t)}
  }`;return{name:"GridSample",shaderCache:{hint:`${t.cacheKey}`,inputDependencies:["type","type"]},getRunData:p=>{let h=M.size(n);return{outputs:[{dims:n,dataType:p[0].dataType}],dispatchGroup:{x:Math.ceil(h/64)},programUniforms:l}},getShaderSource:d}},xl=(e,t)=>{ml(e.inputs),e.compute(vl(e.inputs,t))},Sl=e=>g({alignCorners:e.align_corners,mode:e.mode,paddingMode:e.padding_mode,format:e.format})}),pt,Tl,El,In,kl,aa,Il,Cl=I(()=>{ue(),oe(),b(),si(),nn(),Z(),Ee(),pt=(e,t)=>e.length>t&&e[t].dims.length>0?e[t]:void 0,Tl=(e,t)=>{let r=e[0],i=pt(e,1),a=pt(e,2),n=pt(e,3),s=pt(e,4),o=pt(e,5),u=pt(e,6),l=pt(e,7);if(r.dims.length!==3&&r.dims.length!==5)throw new Error("Input query is expected to have 3 or 5 dimensions");let d=r.dims[0],p=r.dims[1],h=r.dims.length===3?r.dims[2]:t.numHeads*r.dims[4],f=p,m=0,w=0,$=Math.floor(h/t.numHeads);if(u&&l&&M.size(u.dims)&&M.size(l.dims)){if(u.dims.length!==4)throw new Error('Input "past_key" is expected to have 4 dimensions');if(u.dims[0]!==d||u.dims[1]!==t.numHeads||u.dims[3]!==$)throw new Error('Input "past_key" shape (batch_size, num_heads, past_sequence_length, head_size)');if(l.dims[0]!==d||l.dims[1]!==t.numHeads||l.dims[3]!==$)throw new Error('Input "past_value" shape (batch_size, num_heads, past_sequence_length, head_size)');if(u.dims[2]!==l.dims[2])throw new Error('Input "past_key" and "past_value" shall have same dim 2 (past_sequence_length)');if(l.dims.length!==4)throw new Error('Input "past_value" is expected to have 4 dimensions');m=u.dims[2],w=u.dims[2]}else if(u&&M.size(u.dims)||l&&M.size(l.dims))throw new Error('Input "past_key" and "past_value" shall be both present or both absent');let _;if(i&&M.size(i.dims)>0){if(r.dims.length!==3)throw new Error('Input "query" is expected to have 3 dimensions when key is given');if(i.dims.length<3||i.dims.length>5)throw new Error('Input "key" is expected to have 3, 4, or 5 dimensions');if(r.dims[0]!==i.dims[0])throw new Error('Input "query" and "key" shall have same dim 0 (batch size)');if(i.dims.length===3){if(i.dims[2]!==r.dims[2])throw new Error('Input "query" and "key" shall have same dim 2 (hidden_size)');_=2,f=i.dims[1]}else if(i.dims.length===5){if(i.dims[2]!==t.numHeads||i.dims[3]!==2||i.dims[4]!==$)throw new Error('Expect "key" shape (batch_size, kv_sequence_length, num_heads, 2, head_size) for packed kv');if(a)throw new Error('Expect "value" be none when "key" has packed kv format.');_=5,f=i.dims[1]}else{if(i.dims[1]!==t.numHeads||i.dims[3]!==$)throw new Error('Expect "key" shape (batch_size, num_heads, kv_sequence_length, head_size) for past_key');_=0,f=i.dims[2]}}else{if(r.dims.length!==5)throw new Error('Input "query" is expected to have 5 dimensions when key is empty');if(r.dims[2]!==t.numHeads||r.dims[3]!==3)throw new Error('Expect "query" shape (batch_size, kv_sequence_length, num_heads, 3, head_size) for packed kv');_=3}if(n&&M.size(n.dims)>0){if(n.dims.length!==1)throw new Error('Input "bias" is expected to have 1 dimension');if(i&&i.dims.length===5&&i.dims[3]===2)throw new Error("bias is not allowed for packed kv.")}let y=m+f,S=0;if(s&&M.size(s.dims)>0){S=8;let R=s.dims;throw R.length===1?R[0]===d?S=1:R[0]===3*d+2&&(S=3):R.length===2&&R[0]===d&&R[1]===y&&(S=5),S===8?new Error('Input "key_padding_mask" shape shall be (batch_size) or (batch_size, total_sequence_length)'):new Error("Mask not supported")}let v=!1,E=h;if(a&&M.size(a.dims)>0){if(a.dims.length!==3&&a.dims.length!==4)throw new Error('Input "value" is expected to have 3 or 4 dimensions');if(r.dims[0]!==a.dims[0])throw new Error('Input "query" and "value" shall have same dim 0 (batch_size)');if(a.dims.length===3){if(f!==a.dims[1])throw new Error('Input "key" and "value" shall have the same dim 1 (kv_sequence_length)');E=a.dims[2]}else{if(f!==a.dims[2])throw new Error('Input "key" and "value" shall have the same dim 2 (kv_sequence_length)');E=a.dims[1]*a.dims[3],v=!0}}let B=!1;if(s&&M.size(s.dims)>0)throw new Error("Key padding mask is not supported");if(o&&M.size(o.dims)>0){if(o.dims.length!==4)throw new Error('Input "attention_bias" is expected to have 4 dimensions');if(o.dims[0]!==d||o.dims[1]!==t.numHeads||o.dims[2]!==p||o.dims[3]!==y)throw new Error('Expect "attention_bias" shape (batch_size, num_heads, sequence_length, total_sequence_length)')}return{batchSize:d,sequenceLength:p,pastSequenceLength:m,kvSequenceLength:f,totalSequenceLength:y,maxSequenceLength:w,inputHiddenSize:0,hiddenSize:h,vHiddenSize:E,headSize:$,vHeadSize:Math.floor(E/t.numHeads),numHeads:t.numHeads,isUnidirectional:!1,pastPresentShareBuffer:!1,maskFilterValue:t.maskFilterValue,maskType:S,scale:t.scale,broadcastResPosBias:B,passPastInKv:v,qkvFormat:_}},El=e=>g({...e}),In=g({perm:[0,2,1,3]}),kl=(e,t,r,i,a,n,s)=>{let o=[i,a,n],u=M.size(o),l=[{type:12,data:u},{type:12,data:s},{type:12,data:n}],d=p=>{let h=q("qkv_with_bias",t.dataType,o),f=z("qkv",t.dataType,o),m=z("bias",r.dataType,o),w=[{name:"output_size",type:"u32"},{name:"bias_offset",type:"u32"},{name:"hidden_size",type:"u32"}];return`
  ${p.registerUniforms(w).declareVariables(f,m,h)}
  ${p.mainStart()}
    ${p.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
    let bias_offset_idx = (global_idx % uniforms.hidden_size) + uniforms.bias_offset;

    qkv_with_bias[global_idx] = qkv[global_idx] + bias[bias_offset_idx];
  }`};return e.compute({name:"MultiHeadAttentionAddBias",shaderCache:{inputDependencies:["type","type"]},getRunData:()=>({outputs:[{dims:o,dataType:t.dataType,gpuDataType:0}],dispatchGroup:{x:Math.ceil(u/64)},programUniforms:l}),getShaderSource:d},{inputs:[t,r],outputs:[-1]})[0]},aa=(e,t,r,i,a,n,s,o)=>{let u=n;if(s&&M.size(s.dims)>0){if(i===1)throw new Error("AddBiasReshape is not implemented. Please export your model with packed QKV or KV");return u=kl(e,n,s,t,i,r*a,o),u=u.reshape([t,i,r,a]),r===1||i===1?u:e.compute(We(u,In.perm),{inputs:[u],outputs:[-1]})[0]}else return n.dims.length===3&&(u=n.reshape([t,i,r,a])),r===1||i===1?u:e.compute(We(u,In.perm),{inputs:[u],outputs:[-1]})[0]},Il=(e,t)=>{let r=Tl(e.inputs,t),i=e.inputs[0],a=pt(e.inputs,1),n=pt(e.inputs,2),s=pt(e.inputs,3),o=pt(e.inputs,4),u=pt(e.inputs,5),l=pt(e.inputs,6),d=pt(e.inputs,7);if(i.dims.length===5)throw new Error("Packed QKV is not implemented");if(a?.dims.length===5)throw new Error("Packed KV is not implemented");let p=a&&n&&a.dims.length===4&&n.dims.length===4,h=aa(e,r.batchSize,r.numHeads,r.sequenceLength,r.headSize,i,s,0);if(p)return Ji(e,h,a,n,o,void 0,l,d,u,r);if(!a||!n)throw new Error("key and value must be provided");let f=aa(e,r.batchSize,r.numHeads,r.kvSequenceLength,r.headSize,a,s,r.hiddenSize),m=aa(e,r.batchSize,r.numHeads,r.kvSequenceLength,r.vHeadSize,n,s,2*r.hiddenSize);Ji(e,h,f,m,o,void 0,l,d,u,r)}}),zl,Al,Ol,Rl,Cn,Bl,Ml,Dl=I(()=>{ue(),oe(),b(),Z(),zl=e=>{if(!e||e.length<1)throw new Error("too few inputs")},Al=(e,t)=>{let r=[],i=t.numOutputs;return e[1].dims[0]>0&&(e[1].getBigInt64Array().forEach(a=>r.push(Number(a))),i=r.length),g({numOutputs:i,axis:t.axis,splitSizes:r})},Ol=e=>`
fn calculateOutputIndex(index: u32) -> u32 {
    for (var i: u32 = 0u; i < ${e}u; i += 1u ) {
    if (index < ${D("uniforms.size_in_split_axis","i",e)}) {
        return i;
    }
    }
    return ${e}u;
}`,Rl=e=>{let t=e.length,r=[];for(let i=0;i<t;++i){let a=e[i].setByIndices("indices","input[global_idx]");t===1?r.push(a):i===0?r.push(`if (output_number == ${i}u) { ${a} }`):i===t-1?r.push(`else { ${a} }`):r.push(`else if (output_number == ${i}) { ${a} }`)}return`
      fn writeBufferData(output_number: u32, indices: ${e[0].type.indices}, global_idx: u32) {
        ${r.join(`
`)}
      }`},Cn=(e,t)=>{let r=e[0].dims,i=M.size(r),a=e[0].dataType,n=M.normalizeAxis(t.axis,r.length),s=new Array(t.numOutputs),o=z("input",a,r.length),u=new Array(t.numOutputs),l=[],d=[],p=0,h=[{type:12,data:i}];for(let m=0;m<t.numOutputs;m++){p+=t.splitSizes[m],u[m]=p;let w=r.slice();w[n]=t.splitSizes[m],d.push(w),s[m]=q(`output${m}`,a,w.length),l.push({dims:d[m],dataType:e[0].dataType})}h.push({type:12,data:u},...k(r,...d));let f=m=>`
  ${m.registerUniform("input_size","u32").registerUniform("size_in_split_axis","u32",u.length).declareVariables(o,...s)}
  ${Ol(u.length)}
  ${Rl(s)}

  ${m.mainStart()}
    ${m.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.input_size")}

    var indices = ${o.offsetToIndices("global_idx")};
    var index = ${o.indicesGet("indices",n)};
    let output_number = calculateOutputIndex(index);
    if (output_number != 0) {
      index -= ${D("uniforms.size_in_split_axis","output_number - 1u",u.length)};
      ${o.indicesSet("indices",n,"index")};
    }
    writeBufferData(output_number, indices, global_idx);
  }`;return{name:"Split",shaderCache:{hint:t.cacheKey,inputDependencies:["rank"]},getShaderSource:f,getRunData:()=>({outputs:l,dispatchGroup:{x:Math.ceil(i/64)},programUniforms:h})}},Bl=(e,t)=>{zl(e.inputs);let r=e.inputs.length===1?t:Al(e.inputs,t);e.compute(Cn(e.inputs,r),{inputs:[0]})},Ml=e=>{let t=e.axis,r=e.splitSizes,i=e.numOutputs<0?r.length:e.numOutputs;if(i!==r.length)throw new Error("numOutputs and splitSizes length must be equal");return g({axis:t,numOutputs:i,splitSizes:r})}}),Pl,Ba,Ul,Nl=I(()=>{ue(),oe(),b(),Z(),Pl=(e,t)=>{let[r,i,a,n]=e,{numHeads:s,rotaryEmbeddingDim:o}=t;if(r.dims.length!==3&&r.dims.length!==4)throw new Error(`Input 'x' is expected to have 3 or 4 dimensions, got ${r.dims.length}`);if(!M.areEqual(i.dims,[])&&!M.areEqual(i.dims,[1])&&i.dims.length!==2)throw new Error(`Input 'position_ids' is expected to have 0, 1, or 2 dimensions, got ${i.dims.length}`);if(a.dims.length!==2)throw new Error(`Input 'cos_cache' is expected to have 2 dimensions, got ${a.dims.length}`);if(n.dims.length!==2)throw new Error(`Input 'sin_cache' is expected to have 2 dimensions, got ${n.dims.length}`);if(!M.areEqual(a.dims,n.dims))throw new Error("Inputs 'cos_cache' and 'sin_cache' are expected to have the same shape");if(o>0&&s===0)throw new Error("num_heads must be provided if rotary_embedding_dim is specified");let u=r.dims[0],l=r.dims[r.dims.length-2],d=a.dims[0],p=M.sizeFromDimension(r.dims,1)/l,h=o===0?a.dims[1]*2:p/s;if(o>h)throw new Error("rotary_embedding_dim must be less than or equal to head_size");if(i.dims.length===2){if(u!==i.dims[0])throw new Error(`Input 'position_ids' dimension 0 should be of size batch_size, got ${i.dims[0]}`);if(l!==i.dims[1])throw new Error(`Input 'position_ids' dimension 1 should be of size sequence_length, got ${i.dims[1]}`)}if(h/2!==a.dims[1]&&o/2!==a.dims[1])throw new Error(`Input 'cos_cache' dimension 1 should be same as head_size / 2 or rotary_embedding_dim / 2, got ${a.dims[1]}`);if(l>d)throw new Error("Updating cos_cache and sin_cache in RotaryEmbedding is not currently supported")},Ba=(e,t)=>{let{interleaved:r,numHeads:i,rotaryEmbeddingDim:a,scale:n}=t,s=e[0].dims[0],o=M.sizeFromDimension(e[0].dims,1),u=e[0].dims[e[0].dims.length-2],l=o/u,d=e[2].dims[1],p=a===0?d*2:l/i,h=new Array(s,u,l/p,p-d),f=M.computeStrides(h),m=[{type:1,data:n},{type:12,data:h},{type:12,data:f},...e[0].dims.length===3?new Array({type:12,data:[o,l,p,1]}):[],...e[0].dims.length===4?new Array({type:12,data:[o,p,u*p,1]}):[],...k(e[0].dims,e[1].dims,e[2].dims,e[3].dims,e[0].dims)],w=$=>{let _=z("input",e[0].dataType,e[0].dims.length),y=z("position_ids",e[1].dataType,e[1].dims.length),S=z("cos_cache",e[2].dataType,e[2].dims.length),v=z("sin_cache",e[3].dataType,e[3].dims.length),E=q("output",e[0].dataType,e[0].dims.length);return $.registerUniforms([{name:"scale",type:"f32"},{name:"global_shape",type:"u32",length:h.length},{name:"global_strides",type:"u32",length:f.length},{name:"input_output_strides",type:"u32",length:f.length}]),`
        ${$.declareVariables(_,y,S,v,E)}

        ${$.mainStart(T)}
          let half_rotary_emb_dim = uniforms.${S.name}_shape[1];
          let bsnh = global_idx / uniforms.global_strides % uniforms.global_shape;
          let size = uniforms.global_shape[0] * uniforms.global_strides[0];
          ${$.guardAgainstOutOfBoundsWorkgroupSizes("size")}

          if (bsnh[3] < half_rotary_emb_dim) {
            let position_ids_idx =
                ${y.broadcastedIndicesToOffset("bsnh.xy",q("",y.type.tensor,2))};
            let position_id =
                u32(${y.getByOffset("position_ids_idx")}) + select(0, bsnh[1], position_ids_idx == 0);
            let i = dot(bsnh, uniforms.input_output_strides) + select(0, bsnh[3], ${r});
            let j = i + select(half_rotary_emb_dim, 1, ${r});
            let re = ${_.getByOffset("i")} * ${S.get("position_id","bsnh[3]")} -
                ${_.getByOffset("j")} * ${v.get("position_id","bsnh[3]")};
            ${E.setByOffset("i","re")}
            let im = ${_.getByOffset("i")} * ${v.get("position_id","bsnh[3]")} +
                ${_.getByOffset("j")} * ${S.get("position_id","bsnh[3]")};
            ${E.setByOffset("j","im")}
          } else {
            let k = dot(bsnh, uniforms.input_output_strides) + half_rotary_emb_dim;
            ${E.setByOffset("k",_.getByOffset("k"))}
          }
        }`};return{name:"RotaryEmbedding",shaderCache:{hint:g({interleaved:r}).cacheKey,inputDependencies:["rank","rank","rank","rank"]},getShaderSource:w,getRunData:()=>({outputs:[{dims:e[0].dims,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(M.size(h)/T)},programUniforms:m})}},Ul=(e,t)=>{Pl(e.inputs,t),e.compute(Ba(e.inputs,t))}}),Ll,Vl,zn,ql,Fl,Uc=I(()=>{b(),ue(),nn(),Cl(),Dl(),Ee(),Nl(),Z(),Ll=(e,t)=>{if(t.doRotary&&e.length<=7)throw new Error("cos_cache and sin_cache inputs are required if do_rotary is specified");let r=e[0],i=e[1],a=e[2],n=e[3],s=e[4];if(t.doRotary!==0&&e.length<=7)throw new Error("cos_cast and sin_cache are expected if do_rotary attribute is non-zero");if(t.localWindowSize!==-1)throw new Error("Local attention is not supported");if(t.softcap!==0)throw new Error("Softcap is not supported");if(t.rotaryInterleaved!==0)throw new Error("Rotary interleaved is not supported");if(t.smoothSoftmax)throw new Error("Smooth softmax is not supported");if(r.dims.length!==3&&r.dims.length!==5)throw new Error("Input query is expected to have 3 or 5 dimensions");let o=r.dims[0],u=r.dims[1],l=r.dims.length===3?r.dims[2]:t.numHeads*r.dims[4],d=u,p=0,h=!i||i.dims.length===0,f=Math.floor(h?l/(t.numHeads+2*t.kvNumHeads):l/t.numHeads);h&&(l=f*t.numHeads);let m=n&&n.dims.length!==0,w=s&&s.dims.length!==0;if(m&&n.dims.length===4&&n.dims[0]===o&&n.dims[1]!==t.kvNumHeads&&n.dims[2]===t.kvNumHeads&&n.dims[3]===f)throw new Error("BSNH pastKey/pastValue is not supported");if(m&&w){if(n.dims.length!==4)throw new Error('Input "past_key" is expected to have 4 dimensions');if(s.dims.length!==4)throw new Error('Input "past_value" is expected to have 4 dimensions');p=n.dims[2]}else if(m||w)throw new Error('Input "past_key" and "past_value" shall be both present or both absent');let $=1;if(i&&i.dims.length>0){if(r.dims.length!==3)throw new Error('Input "query" is expected to have 3 dimensions when key is given');if(i.dims.length<3||i.dims.length>5)throw new Error('Input "key" is expected to have 3, 4, or 5 dimensions');if(r.dims[0]!==i.dims[0])throw new Error('Input "query" and "key" shall have same dim 0 (batch size)');if(i.dims.length===3){if(r.dims[2]%i.dims[2]!==0)throw new Error('Dimension 2 of "query" should be a multiple of "key"');d=i.dims[1]}else if(i.dims.length===5){if(i.dims[2]!==t.numHeads||i.dims[3]!==2||i.dims[4]!==f)throw new Error('Expect "key" shape (batch_size, kv_sequence_length, num_heads, 2, head_size) for packed kv');if(a)throw new Error('Expect "value" be none when "key" has packed kv format.');d=i.dims[1]}else{if(i.dims[1]!==t.numHeads||i.dims[3]!==f)throw new Error('Expect "key" shape (batch_size, num_heads, kv_sequence_length, head_size) for past_key');d=i.dims[2]}}else{if(r.dims.length!==3&&r.dims.length!==5)throw new Error('Input "query" is expected to have 3 or 5 dimensions when key is empty');if(r.dims.length===5&&(r.dims[2]!==t.numHeads||r.dims[3]!==3))throw new Error('Expect "query" shape (batch_size, kv_sequence_length, num_heads, 3, head_size) for packed kv');$=3}let _=0,y=!1,S=t.kvNumHeads?f*t.kvNumHeads:l;if(a&&a.dims.length>0){if(a.dims.length!==3&&a.dims.length!==4)throw new Error('Input "value" is expected to have 3 or 4 dimensions');if(r.dims[0]!==a.dims[0])throw new Error('Input "query" and "value" shall have same dim 0 (batch_size)');if(a.dims.length===3){if(d!==a.dims[1])throw new Error('Input "key" and "value" shall have the same dim 1 (kv_sequence_length)');S=a.dims[2]}else{if(d!==a.dims[2])throw new Error('Input "past_key" and "past_value" shall have the same dim 2 (kv_sequence_length)');S=a.dims[1]*a.dims[3],y=!0}}let v=e.length>4?e[5]:void 0;if(v&&v.dims.length!==1&&v.dims[0]!==o)throw new Error('Input "seqlens" is expected to have 1 dimension and the same dim 0 as batch_size');return{batchSize:o,sequenceLength:u,pastSequenceLength:p,kvSequenceLength:d,totalSequenceLength:-1,maxSequenceLength:-1,inputHiddenSize:0,hiddenSize:l,vHiddenSize:S,headSize:f,vHeadSize:Math.floor(S/t.kvNumHeads),numHeads:t.numHeads,kvNumHeads:t.kvNumHeads,nReps:t.numHeads/t.kvNumHeads,pastPresentShareBuffer:!1,maskType:_,scale:t.scale,broadcastResPosBias:!1,passPastInKv:y,qkvFormat:$}},Vl=g({perm:[0,2,1,3]}),zn=(e,t,r)=>{let i=t,a=r.kvNumHeads;return t.dims.length===3&&r.kvSequenceLength!==0&&(i=t.reshape([r.batchSize,r.kvSequenceLength,a,r.headSize]),i=e.compute(We(i,Vl.perm),{inputs:[i],outputs:[-1]})[0]),i},ql=(e,t,r,i)=>{let a=7,n=["type","type"],s=[e*t],o=e*t,u=[{type:12,data:o},{type:12,data:t},{type:12,data:e}],l=d=>{let p=z("seq_lens",r.dataType,r.dims),h=z("total_seq_lens",i.dataType,i.dims),f=q("pos_ids",a,s),m=[{name:"output_size",type:"u32"},{name:"sequence_length",type:"u32"},{name:"batch_size",type:"u32"}];return`
  ${d.registerUniforms(m).declareVariables(p,h,f)}
  ${d.mainStart()}
    ${d.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
    let total_sequence_length = u32(${h.getByOffset("0")});
    let is_subsequent_prompt = uniforms.sequence_length > 1 && uniforms.sequence_length != total_sequence_length;
    let is_first_prompt = !is_subsequent_prompt && uniforms.sequence_length == total_sequence_length;
    let batch_idx = global_idx / uniforms.sequence_length;
    let sequence_idx = i32(global_idx % uniforms.sequence_length);
    var pos_id: i32 = 0;
    let seqlen = ${p.getByOffset("batch_idx")};
    let total_seqlen = seqlen + 1;
    if (is_first_prompt) {
      if (sequence_idx < total_seqlen) {
        pos_id = sequence_idx;
      } else {
        pos_id = 1;
      }
      ${f.setByOffset("global_idx","pos_id")}
    } else if (is_subsequent_prompt) {
      let past_seqlen = total_seqlen - i32(uniforms.sequence_length);
      if (past_seqlen + sequence_idx < total_seqlen) {
        pos_id = past_seqlen + sequence_idx;
      } else {
        pos_id = 1;
      }
      ${f.setByOffset("global_idx","pos_id")}
    } else if (global_idx < uniforms.batch_size) {
      ${f.setByOffset("global_idx","seqlen")}
    };
  }
  `};return{name:"GeneratePositionIds",shaderCache:{hint:`${e};${t}`,inputDependencies:n},getRunData:()=>({outputs:[{dims:s,dataType:a}],dispatchGroup:{x:Math.ceil(o/64)},programUniforms:u}),getShaderSource:l}},Fl=(e,t)=>{let r=Ll(e.inputs,t);if(e.inputs[0].dims.length===5)throw new Error("Packed QKV is not implemented");if(e.inputs[1]?.dims.length===5)throw new Error("Packed KV is not implemented");let i=e.inputs[0],a=e.inputs[1]&&e.inputs[1].dims.length>0?e.inputs[1]:void 0,n=e.inputs[2]&&e.inputs[2].dims.length>0?e.inputs[2]:void 0,s=e.inputs[3]&&e.inputs[3].dims.length!==0?e.inputs[3]:void 0,o=e.inputs[4]&&e.inputs[4].dims.length!==0?e.inputs[4]:void 0,u=e.inputs.length>4?e.inputs[5]:void 0,l=e.inputs.length>5?e.inputs[6]:void 0,d=r.kvNumHeads?r.kvNumHeads:r.numHeads,p=g({axis:2,numOutputs:3,splitSizes:[r.numHeads*r.headSize,d*r.headSize,d*r.headSize]}),[h,f,m]=!a&&!n?e.compute(Cn([i],p),{inputs:[i],outputs:[-1,-1,-1]}):[i,a,n],w,$;if(t.doRotary){let v=e.compute(ql(r.batchSize,r.sequenceLength,u,l),{inputs:[u,l],outputs:[-1]})[0],E=e.inputs[7],B=e.inputs[8],R=g({interleaved:t.rotaryInterleaved!==0,numHeads:r.numHeads,rotaryEmbeddingDim:0,scale:t.scale}),U=[h,v,E,B],W=[-1];w=e.compute(Ba(U,R),{inputs:U,outputs:W})[0],U.splice(0,1,f);let X=g({interleaved:t.rotaryInterleaved!==0,numHeads:r.kvNumHeads,rotaryEmbeddingDim:0,scale:t.scale});$=e.compute(Ba(U,X),{inputs:U,outputs:W})[0]}let _=aa(e,r.batchSize,r.numHeads,r.sequenceLength,r.headSize,t.doRotary?w:h,void 0,0),y=zn(e,t.doRotary?$:f,r),S=zn(e,m,r);Ji(e,_,y,S,void 0,void 0,s,o,void 0,r,u,l)}}),An,Wl,Gl,jl,Nc=I(()=>{ue(),oe(),Ee(),Z(),An=(e,t,r,i,a,n,s,o)=>{let u=A(n),l=u===1?"f32":`vec${u}f`,d=u===1?"vec2f":`mat2x${u}f`,p=a*s,h=64;p===1&&(h=256);let f=[a,s,n/u],m=[a,s,2],w=["rank","type","type"],$=[];$.push(...k(f,m));let _=y=>{let S=z("x",t.dataType,3,u),v=z("scale",r.dataType,r.dims),E=z("bias",i.dataType,i.dims),B=q("output",1,3,2),R=[S,v,E,B];return`
  var<workgroup> workgroup_shared : array<${d}, ${h}>;
  const workgroup_size = ${h}u;
  ${y.declareVariables(...R)}
  ${y.mainStart(h)}
    let batch = workgroup_index / uniforms.x_shape[1];
    let channel = workgroup_index % uniforms.x_shape[1];
    let hight = uniforms.x_shape[2];
    // initialize workgroup memory
    var sum = ${l}(0);
    var squared_sum = ${l}(0);
    for (var h = local_idx; h < hight; h += workgroup_size) {
      let value = ${l}(${S.get("batch","channel","h")});
      sum += value;
      squared_sum += value * value;
    }
    workgroup_shared[local_idx] = ${d}(sum, squared_sum);
    workgroupBarrier();

    for (var currSize = workgroup_size >> 1;  currSize > 0; currSize = currSize >> 1) {
      if (local_idx < currSize) {
        workgroup_shared[local_idx] = workgroup_shared[local_idx] + workgroup_shared[local_idx + currSize];
      }
      workgroupBarrier();
    }
    if (local_idx == 0) {
      let sum_final = ${P("workgroup_shared[0][0]",u)} / f32(hight * ${u});
      let squared_sum_final = ${P("workgroup_shared[0][1]",u)} / f32(hight * ${u});

      let inv_std_dev = inverseSqrt(squared_sum_final - sum_final * sum_final + f32(${o}));
      let channel_scale = inv_std_dev * f32(scale[channel]);
      let channel_shift = f32(bias[channel]) - sum_final * channel_scale;
      output[workgroup_index] = vec2f(channel_scale, channel_shift);
    }
  }`};return e.compute({name:"InstanceNormComputeChannelScaleShift",shaderCache:{hint:`${u};${o};${h}`,inputDependencies:w},getRunData:()=>({outputs:[{dims:m,dataType:1}],dispatchGroup:{x:p},programUniforms:$}),getShaderSource:_},{inputs:[t,r,i],outputs:[-1]})[0]},Wl=(e,t,r)=>{let i=t[0].dims,a=i,n=2,s=i[0],o=i[1],u=M.sizeFromDimension(i,n),l=A(u),d=M.size(a)/l,p=An(e,t[0],t[1],t[2],s,u,o,r.epsilon),h=[s,o,u/l],f=[s,o],m=["type","none"],w=$=>{let _=z("x",t[0].dataType,h.length,l),y=z("scale_shift",1,f.length,2),S=q("output",t[0].dataType,h.length,l),v=[_,y,S];return`
  ${$.registerUniform("output_size","u32").declareVariables(...v)}
  ${$.mainStart()}
  ${$.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
      let outputIndices = ${S.offsetToIndices("global_idx")};
      let batch = outputIndices[0];
      let channel = outputIndices[1];
      let scale_shift = ${y.getByIndices("vec2<u32>(batch, channel)")};
      let value = ${_.getByOffset("global_idx")} * ${S.type.value}(scale_shift.x) + ${S.type.value}(scale_shift.y);
      ${S.setByOffset("global_idx","value")};
  }`};e.compute({name:"InstanceNormalization",shaderCache:{hint:`${l}`,inputDependencies:m},getRunData:()=>({outputs:[{dims:a,dataType:t[0].dataType}],dispatchGroup:{x:Math.ceil(d/64)},programUniforms:[{type:12,data:d},...k(h,f,h)]}),getShaderSource:w},{inputs:[t[0],p]})},Gl=(e,t,r)=>{let i=t[0].dims,a=i,n=i[0],s=i[i.length-1],o=M.sizeFromDimension(i,1)/s,u=A(s),l=M.size(a)/u,d=[{type:12,data:o},{type:12,data:Math.floor(s/u)}],p=["type","type"],h=!1,f=[0,i.length-1];for(let _=0;_<i.length-2;_++)h=h||i[_+1]!==1,f.push(_+1);h=h&&i[i.length-1]!==1;let m=h?e.compute(We(e.inputs[0],f),{inputs:[e.inputs[0]],outputs:[-1]})[0]:e.inputs[0].reshape(Array.from({length:i.length},(_,y)=>i[f[y]])),w=An(e,m,t[1],t[2],n,o,s,r.epsilon),$=_=>{let y=O(t[0].dataType),S=u===1?"vec2f":`mat${u}x2f`,v=R=>{let U=R===0?"x":"y",W=u===1?"f32":`vec${u}f`;switch(u){case 1:return`${y}(${W}(scale.${U}))`;case 2:return`vec2<${y}>(${W}(scale[0].${U}, scale[1].${U}))`;case 4:return`vec4<${y}>(${W}(scale[0].${U}, scale[1].${U}, scale[2].${U}, scale[3].${U}))`;default:throw new Error(`Not supported compoents ${u}`)}},E=z("input",t[0].dataType,t[0].dims,u),B=q("output",t[0].dataType,a,u);return`
  @group(0) @binding(0) var<storage, read> input : array<${E.type.storage}>;
  @group(0) @binding(1) var<storage, read> scale_input : array<${S}>;
  @group(0) @binding(2) var<storage, read_write> output : array<${B.type.storage}>;
  struct Uniforms {H: u32, C : u32};
  @group(0) @binding(3) var<uniform> uniforms: Uniforms;

  ${_.mainStart()}
    let current_image_number = global_idx / (uniforms.C * uniforms.H);
    let current_channel_number = global_idx % uniforms.C;

    let scale_offset = current_image_number * uniforms.C + current_channel_number;
    let scale = scale_input[scale_offset];
    output[global_idx] = fma(input[global_idx], ${v(0)}, ${v(1)});
  }`};e.compute({name:"InstanceNormalizationNHWC",shaderCache:{hint:`${u}`,inputDependencies:p},getRunData:()=>({outputs:[{dims:a,dataType:t[0].dataType}],dispatchGroup:{x:Math.ceil(l/64)},programUniforms:d}),getShaderSource:$},{inputs:[t[0],w]})},jl=(e,t)=>{t.format==="NHWC"?Gl(e,e.inputs,t):Wl(e,e.inputs,t)}}),Hl,Kl,Zl,Lc=I(()=>{ue(),oe(),Z(),Hl=e=>{if(!e||e.length<2)throw new Error("layerNorm requires at least 2 inputs.")},Kl=(e,t,r)=>{let i=t.simplified,a=e[0].dims,n=e[1],s=!i&&e[2],o=a,u=M.normalizeAxis(t.axis,a.length),l=M.sizeToDimension(a,u),d=M.sizeFromDimension(a,u),p=M.size(n.dims),h=s?M.size(s.dims):0;if(p!==d||s&&h!==d)throw new Error(`Size of X.shape()[axis:] == ${d}.
       Size of scale and bias (if provided) must match this.
       Got scale size of ${p} and bias size of ${h}`);let f=[];for(let E=0;E<a.length;++E)E<u?f.push(a[E]):f.push(1);let m=A(d),w=["type","type"],$=[{type:12,data:l},{type:1,data:d},{type:12,data:Math.floor(d/m)},{type:1,data:t.epsilon}];s&&w.push("type");let _=r>1,y=r>2,S=E=>{let B=O(e[0].dataType),R=[z("x",e[0].dataType,e[0].dims,m),z("scale",n.dataType,n.dims,m)];s&&R.push(z("bias",s.dataType,s.dims,m)),R.push(q("output",e[0].dataType,o,m)),_&&R.push(q("mean_data_output",1,f)),y&&R.push(q("inv_std_output",1,f));let U=[{name:"norm_count",type:"u32"},{name:"norm_size",type:"f32"},{name:"norm_size_vectorized",type:"u32"},{name:"epsilon",type:"f32"}];return`
  ${E.registerUniforms(U).declareVariables(...R)}
  ${E.mainStart()}
    ${E.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.norm_count")}
    let offset = global_idx * uniforms.norm_size_vectorized;
    var mean_vector = ${N("f32",m)};
    var mean_square_vector = ${N("f32",m)};

    for (var h: u32 = 0u; h < uniforms.norm_size_vectorized; h++) {
      let value = ${V(B,m,"x[h + offset]")};
      mean_vector += value;
      mean_square_vector += value * value;
    }
    let mean = ${P("mean_vector",m)} / uniforms.norm_size;
    let inv_std_dev = inverseSqrt(${P("mean_square_vector",m)} / uniforms.norm_size ${i?"":"- mean * mean"} + uniforms.epsilon);

    for (var j: u32 = 0; j < uniforms.norm_size_vectorized; j++) {
      let f32input = ${V(B,m,"x[j + offset]")};
      let f32scale = ${V(B,m,"scale[j]")};
      output[j + offset] = ${R[0].type.value}((f32input ${i?"":"- mean"}) * inv_std_dev * f32scale
        ${s?`+ ${V(B,m,"bias[j]")}`:""}
      );
    }

    ${_?"mean_data_output[global_idx] = mean":""};
    ${y?"inv_std_output[global_idx] = inv_std_dev":""};
  }`},v=[{dims:o,dataType:e[0].dataType}];return _&&v.push({dims:f,dataType:1}),y&&v.push({dims:f,dataType:1}),{name:"LayerNormalization",shaderCache:{hint:`${m};${r};${i}`,inputDependencies:w},getRunData:()=>({outputs:v,dispatchGroup:{x:Math.ceil(l/64)},programUniforms:$}),getShaderSource:S}},Zl=(e,t)=>{Hl(e.inputs),e.compute(Kl(e.inputs,t,e.outputCount))}}),Ql,Xl,Vc=I(()=>{oe(),hn(),yn(),Ql=e=>{if(!e||e.length!==2)throw new Error("MatMul requires 2 inputs.");if(e[0].dims[e[0].dims.length-1]!==e[1].dims[e[1].dims.length-2])throw new Error("shared dimension does not match.")},Xl=e=>{Ql(e.inputs);let t=Lt.calcShape(e.inputs[0].dims,e.inputs[1].dims,!0);if(!t)throw new Error("Can't use matmul on the given tensors");let r=t[t.length-1],i=e.inputs[0].dims[e.inputs[0].dims.length-1];if(r<8&&i<8)e.compute(cn(e.inputs,{activation:""},t));else{let a=t[t.length-2],n=M.size(e.inputs[0].dims.slice(0,-2)),s=M.size(e.inputs[1].dims.slice(0,-2));if(n!==1&&a===1&&s===1){let o=e.inputs[0].reshape([1,n,i]),u=e.inputs[1].reshape([1,i,r]),l=[1,n,r],d=[o,u];e.compute(za(d,{activation:""},t,l),{inputs:d})}else e.compute(za(e.inputs,{activation:""},t))}}}),Yl,Jl,ed,td,rd,qc=I(()=>{ue(),oe(),b(),Z(),Yl=(e,t)=>{if(e.length<3||e.length>4)throw new Error("MatMulNBits requires 3 or 4 inputs");let r=e[0],i=r.dims.length;if(r.dims[i-1]!==t.k)throw new Error("The last dim of input shape does not match the k value");let a=Math.floor((t.k+t.blockSize-1)/t.blockSize),n=t.blockSize/8*t.bits,s=e[1];if(!M.areEqual(s.dims,[t.n,a,n]))throw new Error("The second inputs must be 3D tensor with shape N X nBlocksPerCol X blobSize");let o=e[2].dims;if(M.size(o)!==t.n*a)throw new Error("scales input size error.");if(e.length===4){let u=e[3].dims,l=t.n*(t.bits===8?a:Math.floor((a*t.bits+7)/8));if(M.size(u)!==l)throw new Error("zeroPoints input size error.")}},Jl=(e,t)=>{let r=e[0].dims,i=r.length,a=r[i-2],n=t.k,s=t.n,o=r.slice(0,i-2),u=M.size(o),l=e[1].dims[2]/4,d=e[0].dataType,p=A(t.k),h=A(l),f=A(s),m=o.concat([a,s]),w=a>1&&s/f%2===0?2:1,$=M.size(m)/f/w,_=64,y=[],S=[u,a,n/p],v=M.convertShape(e[1].dims).slice();v.splice(-1,1,l/h),y.push(...k(S)),y.push(...k(v)),y.push(...k(e[2].dims)),e.length===4&&y.push(...k(M.convertShape(e[3].dims)));let E=[u,a,s/f];y.push(...k(E));let B=R=>{let U=S.length,W=z("a",e[0].dataType,U,p),X=z("b",12,v.length,h),ke=z("scales",e[2].dataType,e[2].dims.length),ae=[W,X,ke],de=e.length===4?z("zero_points",12,e[3].dims.length):void 0;de&&ae.push(de);let Me=E.length,j=q("output",e[0].dataType,Me,f),re=O(e[0].dataType),Ie=(()=>{switch(p){case 1:return`array<${re}, 8>`;case 2:return`mat4x2<${re}>`;case 4:return`mat2x4<${re}>`;default:throw new Error(`${p}-component is not supported.`)}})(),be=()=>{let L=`
          // reuse a data
            var input_offset = ${W.indicesToOffset(`${W.type.indices}(batch, row, word_offset)`)};
            var a_data: ${Ie};
            for (var j: u32 = 0; j < ${8/p}; j++) {
              a_data[j] = ${W.getByOffset("input_offset")};
              input_offset++;
            }
          `;for(let K=0;K<f*w;K++)L+=`
            b_value = ${h===1?`b${K}_data`:`b${K}_data[i]`};
            b_value_lower = unpack4xU8(b_value & b_mask);
            b_value_upper = unpack4xU8((b_value >> 4) & b_mask);
            b_quantized_values = ${Ie}(${Array.from({length:4},($e,Pe)=>`${re}(b_value_lower[${Pe}]), ${re}(b_value_upper[${Pe}])`).join(", ")});
            b_dequantized_values = ${p===1?`${Ie}(${Array.from({length:8},($e,Pe)=>`(b_quantized_values[${Pe}] - ${de?`zero_point${K}`:"zero_point"}) * scale${K}`).join(", ")});`:`(b_quantized_values - ${Ie}(${Array(8).fill(`${de?`zero_point${K}`:"zero_point"}`).join(",")})) * scale${K};`};
            workgroup_shared[local_id.x * ${w} + ${Math.floor(K/f)}]${f>1?`[${K%f}]`:""} += ${Array.from({length:8/p},($e,Pe)=>`${p===1?`a_data[${Pe}] * b_dequantized_values[${Pe}]`:`dot(a_data[${Pe}], b_dequantized_values[${Pe}])`}`).join(" + ")};
          `;return L},fe=()=>{let L=`
            var col_index = col * ${f};
            ${de?`
            let zero_point_bytes_per_col = (nBlocksPerCol + 1) / 2;
            var zero_point_byte_count: u32;
            var zero_point_word_index: u32;
            var zero_point_byte_offset: u32;
            let zero_point_nibble_offset: u32 = block & 0x1u;
            var zero_point_bits_offset: u32;
            var zero_point_word: u32;`:`
            // The default zero point is 8 for unsigned 4-bit quantization.
            let zero_point = ${re}(8);`}
            `;for(let K=0;K<f*w;K++)L+=`
            let scale${K} = ${ke.getByOffset("col_index * nBlocksPerCol + block")};
            ${de?`
            zero_point_byte_count = col_index * zero_point_bytes_per_col + (block >> 0x1u);
            zero_point_word_index = zero_point_byte_count >> 0x2u;
            zero_point_byte_offset = zero_point_byte_count & 0x3u;
            zero_point_bits_offset = (zero_point_byte_offset << 3) + (zero_point_nibble_offset << 2);
            zero_point_word = ${de.getByOffset("zero_point_word_index")} >> zero_point_bits_offset;
            let zero_point${K} = ${re}((zero_point_word) & 0xFu);`:""}
            col_index += 1;`;return L},De=()=>{let L=`col_index = col * ${f};`;for(let K=0;K<f*w;K++)L+=`
            let b${K}_data = ${X.getByIndices(`${X.type.indices}(col_index, block, word)`)};
            col_index += 1;`;return L+=`
            var b_value: u32;
            let b_mask: u32 = 0x0F0F0F0Fu;
            var b_value_lower: vec4<u32>;
            var b_value_upper: vec4<u32>;
            var b_quantized_values: ${Ie};
            var b_dequantized_values: ${Ie};`,L};return`
        var<workgroup> workgroup_shared: array<${j.type.value}, ${w*_}>;
        ${R.declareVariables(...ae,j)}
        ${R.mainStart([_,1,1])}
          let output_indices = ${j.offsetToIndices(`(global_idx / ${_}) * ${w}`)};
          let col = output_indices[2];
          let row = output_indices[1];
          let batch = output_indices[0];
          let nBlocksPerCol = uniforms.b_shape[1];

          for (var block = local_id.x; block < nBlocksPerCol; block += ${_}) {
            //process one block
            var word_offset: u32 = block * ${t.blockSize/p};
            ${fe()}
            for (var word: u32 = 0; word < ${l}; word += ${h}) {
              ${De()}
              for (var i: u32 = 0; i < ${h}; i++) {
                ${be()}
                word_offset += ${8/p};
              }
            }
          }
          workgroupBarrier();

          if (local_id.x < ${w}) {
            var output_value: ${j.type.value} = ${j.type.value}(0);
            var workgroup_shared_offset: u32 = local_id.x;
            for (var b: u32 = 0u; b < ${_}u; b++) {
              output_value += workgroup_shared[workgroup_shared_offset];
              workgroup_shared_offset += ${w};
            }
            ${j.setByIndices(`${j.type.indices}(batch, row, col + local_id.x)`,"output_value")};
          }
        }`};return{name:"MatMulNBits",shaderCache:{hint:`${t.blockSize};${t.bits};${p};${h};${f};${w};${_}`,inputDependencies:Array(e.length).fill("rank")},getRunData:()=>({outputs:[{dims:m,dataType:d}],dispatchGroup:{x:$},programUniforms:y}),getShaderSource:B}},ed=(e,t)=>{let r=e[0].dims,i=r.length,a=r[i-2],n=t.k,s=t.n,o=r.slice(0,i-2),u=M.size(o),l=e[1].dims[2]/4,d=e[0].dataType,p=A(t.k),h=A(l),f=o.concat([a,s]),m=128,w=s%8===0?8:s%4===0?4:1,$=m/w,_=$*h*8,y=_/p,S=_/t.blockSize,v=M.size(f)/w,E=[],B=[u,a,n/p],R=M.convertShape(e[1].dims).slice();R.splice(-1,1,l/h),E.push(...k(B)),E.push(...k(R)),E.push(...k(e[2].dims)),e.length===4&&E.push(...k(M.convertShape(e[3].dims)));let U=[u,a,s];E.push(...k(U));let W=X=>{let ke=B.length,ae=z("a",e[0].dataType,ke,p),de=z("b",12,R.length,h),Me=z("scales",e[2].dataType,e[2].dims.length),j=[ae,de,Me],re=e.length===4?z("zero_points",12,e[3].dims.length):void 0;re&&j.push(re);let Ie=U.length,be=q("output",e[0].dataType,Ie),fe=O(e[0].dataType),De=()=>{switch(p){case 1:return`
          let a_data0 = vec4<${fe}>(sub_a[word_offset], sub_a[word_offset + 1], sub_a[word_offset + 2], sub_a[word_offset + 3]);
          let a_data1 = vec4<${fe}>(sub_a[word_offset + 4], sub_a[word_offset + 5], sub_a[word_offset + 6], sub_a[word_offset + 7]);`;case 2:return`
          let a_data0 = vec4<${fe}>(sub_a[word_offset], sub_a[word_offset + 1]);
          let a_data1 = vec4<${fe}>(sub_a[word_offset + 2], sub_a[word_offset + 3]);`;case 4:return`
          let a_data0 = sub_a[word_offset];
          let a_data1 = sub_a[word_offset + 1];`;default:throw new Error(`${p}-component is not supported.`)}};return`
        var<workgroup> sub_a: array<${ae.type.value}, ${y}>;
        var<workgroup> inter_results: array<array<${be.type.value}, ${$}>, ${w}>;
        ${X.declareVariables(...j,be)}
        ${X.mainStart([$,w,1])}
          let output_indices = ${be.offsetToIndices(`workgroup_index * ${w}`)};
          let col = output_indices[2];
          let row = output_indices[1];
          let batch = output_indices[0];
          let n_blocks_per_col = uniforms.b_shape[1];
          let num_tiles =  (n_blocks_per_col - 1) / ${S} + 1;

          // Loop over shared dimension.
          for (var tile: u32 = 0; tile < num_tiles; tile += 1) {
            let a_col_start = tile * ${y};
            // load one tile A data into shared memory.
            for (var a_offset = local_idx; a_offset < ${y}; a_offset += ${m})
            {
              let a_col = a_col_start + a_offset;
              if (a_col < uniforms.a_shape[2])
              {
                sub_a[a_offset] = ${ae.getByIndices(`${ae.type.indices}(batch, row, a_col)`)};
              } else {
                sub_a[a_offset] = ${ae.type.value}(0);
              }
            }
            workgroupBarrier();

            // each thread process one block
            let b_row = col + local_id.y;
            let block = tile * ${S} + local_id.x;
            ${re?`
            let zero_point_bytes_per_col = (n_blocks_per_col + 1) / 2;
            let zero_point_byte_count = b_row * zero_point_bytes_per_col + (block >> 0x1u);
            let zero_point_word_index = zero_point_byte_count >> 0x2u;
            let zero_point_byte_offset = zero_point_byte_count & 0x3u;
            let zero_point_nibble_offset: u32 = block & 0x1u;
            let zero_point_bits_offset = (zero_point_byte_offset << 3) + (zero_point_nibble_offset << 2);
            let zero_point_word = ${re.getByOffset("zero_point_word_index")} >> zero_point_bits_offset;
            let zero_point = ${fe}((zero_point_word) & 0xFu);`:`
            // The default zero point is 8 for unsigned 4-bit quantization.
            let zero_point = ${fe}(8);`}
            let scale = ${Me.getByOffset("b_row * n_blocks_per_col + block")};
            let b_data = ${de.getByIndices(`${de.type.indices}(b_row, block, 0)`)};
            var word_offset = local_id.x * ${t.blockSize/p};
            for (var i: u32 = 0; i < ${h}; i++) {
              ${De()}
              let b_value = ${h===1?"b_data":"b_data[i]"};
              let b_value_lower = unpack4xU8(b_value & 0x0F0F0F0Fu);
              let b_value_upper = unpack4xU8((b_value >> 4) & 0x0F0F0F0Fu);
              let b_quantized_values = mat2x4<${fe}>(${Array.from({length:4},(L,K)=>`${fe}(b_value_lower[${K}]), ${fe}(b_value_upper[${K}])`).join(", ")});
              let b_dequantized_values = (b_quantized_values - mat2x4<${fe}>(${Array(8).fill("zero_point").join(",")})) * scale;
              inter_results[local_id.y][local_id.x] += ${Array.from({length:2},(L,K)=>`${`dot(a_data${K}, b_dequantized_values[${K}])`}`).join(" + ")};
              word_offset += ${8/p};
            }
            workgroupBarrier();
          }

          if (local_idx < ${w}) {
            var output_value: ${be.type.value} = ${be.type.value}(0);
            for (var b = 0u; b < ${$}; b++) {
              output_value += inter_results[local_idx][b];
            }
            if (col + local_idx < uniforms.output_shape[2])
            {
              ${be.setByIndices(`${be.type.indices}(batch, row, col + local_idx)`,"output_value")}
            }
          }
        }`};return{name:"BlockwiseMatMulNBits32",shaderCache:{hint:`${t.blockSize};${p};${h};${$};${w}`,inputDependencies:Array(e.length).fill("rank")},getRunData:()=>({outputs:[{dims:f,dataType:d}],dispatchGroup:{x:v},programUniforms:E}),getShaderSource:W}},td=(e,t)=>{Yl(e.inputs,t),t.blockSize===32&&e.adapterInfo.isVendor("intel")&&e.adapterInfo.isArchitecture("gen-12lp")?e.compute(ed(e.inputs,t)):e.compute(Jl(e.inputs,t))},rd=e=>g(e)}),id,ad,nd,sd,od,ud,ld,dd,pd,Fc=I(()=>{ue(),oe(),Z(),id=e=>{if(!e||e.length<1)throw new Error("Too few inputs");if(e[0].dataType!==1&&e[0].dataType!==10)throw new Error("Input type must be float or float16.");if(e.length>=2){let t=e[0].dims.length*2===e[1].dims[0];if(e.length===4&&(t=e[3].dims[0]*2===e[1].dims[0]),!t)throw new Error("The pads should be a 1D tensor of shape [2 * input_rank] or [2 * num_axes].")}},ad=(e,t,r)=>{let i="";for(let a=t-1;a>=0;--a)i+=`
            k = i32(${e.indicesGet("indices",a)}) - ${D("uniforms.pads",a,r)};
            if (k < 0) {
              break;
            }
            if (k >= i32(${D("uniforms.x_shape",a,t)})) {
              break;
            }
            offset += k * i32(${D("uniforms.x_strides",a,t)});
        `;return`
          value = ${e.type.value}(uniforms.constant_value);
          for (var i = 0; i < 1; i++) {
            var offset = 0;
            var k = 0;
            ${i}
            value = x[offset];
          }
      `},nd=(e,t,r)=>{let i="";for(let a=t-1;a>=0;--a)i+=`
                k = i32(${e.indicesGet("indices",a)}) - ${D("uniforms.pads",a,r)};
                if (k < 0) {
                  k = -k;
                }
                {
                  let _2n_1 = 2 * (i32(${D("uniforms.x_shape",a,t)}) - 1);
                  k = k % _2n_1;
                  if(k >= i32(${D("uniforms.x_shape",a,t)})) {
                    k = _2n_1 - k;
                  }
                }
                offset += k * i32(${D("uniforms.x_strides",a,t)});
            `;return`
              var offset = 0;
              var k = 0;
              ${i}
              value = x[offset];
          `},sd=(e,t,r)=>{let i="";for(let a=t-1;a>=0;--a)i+=`
                k = i32(${e.indicesGet("indices",a)}) - ${D("uniforms.pads",a,r)};
                if (k < 0) {
                  k = 0;
                }
                if (k >= i32(${D("uniforms.x_shape",a,t)})) {
                  k = i32(${D("uniforms.x_shape",a,t)}) - 1;
                }
                offset += k * i32(${D("uniforms.x_strides",a,t)});
            `;return`
              var offset = 0;
              var k = 0;
              ${i}
              value = x[offset];
          `},od=(e,t,r)=>{let i="";for(let a=t-1;a>=0;--a)i+=`
                k = i32(${e.indicesGet("indices",a)}) - ${D("uniforms.pads",a,r)};
                if (k < 0)  {
                  k += i32(${D("uniforms.x_shape",a,t)}]);
                }
                if (k >= i32(${D("uniforms.x_shape",a,t)})) {
                  k -= i32(${D("uniforms.x_shape",a,t)});
                }
                offset += k * i32(${D("uniforms.x_strides",a,t)});
            `;return`
              var offset = 0;
              var k = 0;
              ${i}
              value = x[offset];
          `},ud=(e,t,r)=>{switch(r.mode){case 0:return ad(e,t,r.pads.length);case 1:return nd(e,t,r.pads.length);case 2:return sd(e,t,r.pads.length);case 3:return od(e,t,r.pads.length);default:throw new Error("Invalid mode")}},ld=(e,t)=>{let r=M.padShape(e[0].dims.slice(),t.pads),i=e[0].dims,a=M.size(r),n=[{type:12,data:a},{type:6,data:t.pads}],s=e.length>=3&&e[2].data;t.mode===0&&n.push({type:s?e[2].dataType:1,data:t.value}),n.push(...k(e[0].dims,r));let o=["rank"],u=l=>{let d=q("output",e[0].dataType,r.length),p=z("x",e[0].dataType,i.length),h=p.type.value,f=ud(d,i.length,t),m=[{name:"output_size",type:"u32"},{name:"pads",type:"i32",length:t.pads.length}];return t.mode===0&&m.push({name:"constant_value",type:s?h:"f32"}),`
            ${l.registerUniforms(m).declareVariables(p,d)}
            ${l.mainStart()}
            ${l.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}

            let indices = ${d.offsetToIndices("global_idx")};

            var value = ${h}(0);
            ${f}
            output[global_idx] = value;
        }`};return{name:"Pad",shaderCache:{hint:`${t.mode}${s}`,inputDependencies:o},getRunData:()=>({outputs:[{dims:r,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(M.size(r)/64)},programUniforms:n}),getShaderSource:u}},dd=(e,t)=>{if(e.length>1){let r=e[1].getBigInt64Array(),i=e.length>=3&&e[2].data?e[2].dataType===10?e[2].getUint16Array()[0]:e[2].getFloat32Array()[0]:0,a=e[0].dims.length,n=new Int32Array(2*a).fill(0);if(e.length>=4){let o=e[3].getBigInt64Array();for(let u=0;u<o.length;u++)n[Number(o[u])]=Number(r[u]),n[Number(o[u])+a]=Number(r[u+o.length])}else r.forEach((o,u)=>n[Number(u)]=Number(o));let s=[];return n.forEach(o=>s.push(o)),{mode:t.mode,value:i,pads:s}}else return t},pd=(e,t)=>{id(e.inputs);let r=dd(e.inputs,t);e.compute(ld(e.inputs,r),{inputs:[0]})}}),na,On,Rn,Bn,Mn,cd,hd,Dn,Pn,fd,md,Un,gd,yd,Nn,wd,_d,bd,$d,Wc=I(()=>{Ye(),ue(),oe(),Z(),na=e=>{if(ie.webgpu.validateInputContent&&(!e||e.length!==1))throw new Error("Pool ops requires 1 input.")},On=(e,t,r)=>{let i=t.format==="NHWC",a=e.dims.slice();i&&a.splice(1,0,a.pop());let n=Object.hasOwnProperty.call(t,"dilations"),s=t.kernelShape.slice(),o=t.strides.slice(),u=n?t.dilations.slice():[],l=t.pads.slice();rr.adjustPoolAttributes(r,a,s,o,u,l);let d=rr.computePoolOutputShape(r,a,o,u,s,l,t.autoPad),p=Object.assign({},t);n?Object.assign(p,{kernelShape:s,strides:o,pads:l,dilations:u,cacheKey:t.cacheKey}):Object.assign(p,{kernelShape:s,strides:o,pads:l,cacheKey:t.cacheKey});let h=d.slice();return h.push(h.splice(1,1)[0]),[p,i?h:d]},Rn=(e,t)=>{let r=t.format==="NHWC",i=M.size(e),a=M.size(t.kernelShape),n=[{type:12,data:i},{type:12,data:a}],s=[{name:"outputSize",type:"u32"},{name:"kernelSize",type:"u32"}];if(t.kernelShape.length<=2){let o=t.kernelShape[t.kernelShape.length-1],u=t.strides[t.strides.length-1],l=t.pads[t.pads.length/2-1],d=t.pads[t.pads.length-1],p=!!(l+d);n.push({type:12,data:o},{type:12,data:u},{type:12,data:l},{type:12,data:d}),s.push({name:"kw",type:"u32"},{name:"sw",type:"u32"},{name:"pwStart",type:"u32"},{name:"pwEnd",type:"u32"});let h=!1;if(t.kernelShape.length===2){let f=t.kernelShape[t.kernelShape.length-2],m=t.strides[t.strides.length-2],w=t.pads[t.pads.length/2-2],$=t.pads[t.pads.length-2];h=!!(w+$),n.push({type:12,data:f},{type:12,data:m},{type:12,data:w},{type:12,data:$}),s.push({name:"kh",type:"u32"},{name:"sh",type:"u32"},{name:"phStart",type:"u32"},{name:"phEnd",type:"u32"})}return[n,s,!0,p,h]}else{if(r)throw new Error("Pooling with kernelShape.length > 2 is not supported for NHWC format.");let o=M.computeStrides(t.kernelShape);n.push({type:12,data:o},{type:12,data:t.pads},{type:12,data:t.strides}),s.push({name:"kernelStrides",type:"u32",length:o.length},{name:"pads",type:"u32",length:t.pads.length},{name:"strides",type:"u32",length:t.strides.length});let u=t.pads.reduce((l,d)=>l+d);return[n,s,!!u,!1,!1]}},Bn=(e,t,r,i,a,n,s,o,u,l,d,p)=>{let h=a.format==="NHWC",f=t.type.value,m=q("output",t.type.tensor,i);if(a.kernelShape.length<=2){let w="",$="",_="",y=r-(h?2:1);if(d?w=`
                for (var i: u32 = 0u; i < uniforms.kw; i++) {
                  xIndices[${y}] = indices[${y}] * uniforms.sw - uniforms.pwStart + i;
                  if (xIndices[${y}] < 0 || xIndices[${y}]
                      >= uniforms.x_shape[${y}]) {
                    pad++;
                    continue;
                  }
                  let x_val = x[${t.indicesToOffset("xIndices")}];
                  ${n}
                }`:w=`
                for (var i: u32 = 0u; i < uniforms.kw; i++) {
                  xIndices[${y}] = indices[${y}] * uniforms.sw - uniforms.pwStart + i;
                  let x_val = x[${t.indicesToOffset("xIndices")}];
                  ${n}
                }`,a.kernelShape.length===2){let S=r-(h?3:2);p?$=`
                for (var j: u32 = 0u; j < uniforms.kh; j++) {
                  xIndices[${S}] = indices[${S}] * uniforms.sh - uniforms.phStart + j;
                  if (xIndices[${S}] < 0 || xIndices[${S}] >= uniforms.x_shape[${S}]) {
                    pad += i32(uniforms.kw);
                    continue;
                  }
              `:$=`
                for (var j: u32 = 0u; j < uniforms.kh; j++) {
                  xIndices[${S}] = indices[${S}] * uniforms.sh - uniforms.phStart + j;
                `,_=`
              }
            `}return`
            ${e.registerUniforms(u).declareVariables(t,m)}

            ${e.mainStart()}
              ${e.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}

              let indices = ${m.offsetToIndices("global_idx")};
              var xIndices = ${m.offsetToIndices("global_idx")};

              var value = ${f}(${o});
              var pad = 0;
              ${$}
              ${w}
              ${_}
              ${s}

              output[global_idx] = value;
            }`}else{if(h)throw new Error("Pooling with kernelShape.length > 2 is not supported for NHWC format.");let w=a.kernelShape.length,$=a.pads.length,_="";return l?_=`
                if (xIndices[j] >= uniforms.x_shape[j]) {
                  pad++;
                  isPad = true;
                  break;
                }
              }
              if (!isPad) {
                let x_val = x[${t.indicesToOffset("xIndices")}];
                ${n}
              }`:_=`
              }
              let x_val = x[${t.indicesToOffset("xIndices")}];
              ${n}
            `,`
            ${e.registerUniforms(u).declareVariables(t,m)}

            ${e.mainStart()}
              ${e.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}
              let indices = ${m.offsetToIndices("global_idx")};
              var xIndices = ${m.offsetToIndices("global_idx")};

              var offsets: array<u32, ${w}>;

              var value = ${f}(${o});
              var pad = 0;
              var isPad = false;

              for (var i: u32 = 0u; i < uniforms.kernelSize; i++) {
                var offset = i;
                for (var j = 0u; j < ${w-1}u; j++) {
                  offsets[j] = offset / ${D("uniforms.kernelStrides","j",w)};
                  offset -= offsets[j] * ${D("uniforms.kernelStrides","j",w)};
                }
                offsets[${w-1}] = offset;

                isPad = false;
                for (var j = ${r-w}u; j < ${r}u; j++) {
                  xIndices[j] = indices[j] * ${D("uniforms.strides",`j - ${r-w}u`,w)}
                    + offsets[j - ${r-w}u] - ${D("uniforms.pads","j - 2u",$)};
                  ${_}
              }
              ${s}

              output[global_idx] = value;
            }`}},Mn=e=>`${e.format};${e.ceilMode};${e.autoPad};${e.kernelShape.length}`,cd=e=>`${Mn(e)};${e.countIncludePad}`,hd=e=>`${Mn(e)};${e.storageOrder};${e.dilations}`,Dn=e=>({format:e.format,autoPad:["NOTSET","VALID","SAME_UPPER","SAME_LOWER"][e.auto_pad],ceilMode:e.ceil_mode,kernelShape:e.kernel_shape,strides:e.strides,pads:e.pads}),Pn=(e,t,r,i)=>{let[a,n]=On(t,i,r),s=z("x",t.dataType,t.dims.length),o=s.type.value,u="value += x_val;",l="";a.countIncludePad?l+=`value /= ${o}(uniforms.kernelSize);`:l+=`value /= ${o}(i32(uniforms.kernelSize) - pad);`;let[d,p,h,f,m]=Rn(n,a);d.push(...k(t.dims,n));let w=["rank"];return{name:e,shaderCache:{hint:`${i.cacheKey};${h};${f};${m}`,inputDependencies:w},getRunData:()=>({outputs:[{dims:n,dataType:t.dataType}],dispatchGroup:{x:Math.ceil(M.size(n)/64)},programUniforms:d}),getShaderSource:$=>Bn($,s,t.dims.length,n.length,a,u,l,0,p,h,f,m)}},fd=e=>{let t=e.count_include_pad!==0,r=Dn(e);if(r.ceilMode!==0)throw new Error("using ceil() in shape computation is not yet supported for AveragePool");let i={countIncludePad:t,...r,cacheKey:""};return{...i,cacheKey:cd(i)}},md=(e,t)=>{na(e.inputs),e.compute(Pn("AveragePool",e.inputs[0],!1,t))},Un={autoPad:"",ceilMode:0,countIncludePad:!1,kernelShape:[],strides:[],pads:[],storageOrder:0,dilations:[]},gd=e=>{let t=e.format;return{format:t,...Un,cacheKey:t}},yd=(e,t)=>{na(e.inputs),e.compute(Pn("GlobalAveragePool",e.inputs[0],!0,t))},Nn=(e,t,r,i)=>{let[a,n]=On(t,i,r),s=`
      value = max(x_val, value);
    `,o="",u=z("x",t.dataType,t.dims.length),l=["rank"],[d,p,h,f,m]=Rn(n,a);return d.push(...k(t.dims,n)),{name:e,shaderCache:{hint:`${i.cacheKey};${h};${f};${m}`,inputDependencies:l},getRunData:()=>({outputs:[{dims:n,dataType:t.dataType}],dispatchGroup:{x:Math.ceil(M.size(n)/64)},programUniforms:d}),getShaderSource:w=>Bn(w,u,t.dims.length,n.length,a,s,o,t.dataType===10?-65504:-1e5,p,h,f,m)}},wd=(e,t)=>{na(e.inputs),e.compute(Nn("MaxPool",e.inputs[0],!1,t))},_d=e=>{let t=e.storage_order,r=e.dilations,i=Dn(e);if(t!==0)throw new Error("column major storage order is not yet supported for MaxPool");if(i.ceilMode!==0)throw new Error("using ceil() in shape computation is not yet supported for MaxPool");let a={storageOrder:t,dilations:r,...i,cacheKey:""};return{...a,cacheKey:hd(a)}},bd=e=>{let t=e.format;return{format:t,...Un,cacheKey:t}},$d=(e,t)=>{na(e.inputs),e.compute(Nn("GlobalMaxPool",e.inputs[0],!0,t))}}),vd,xd,Sd,Td,Gc=I(()=>{ue(),oe(),b(),Z(),vd=(e,t)=>{if(e.length<2||e.length>3)throw new Error("DequantizeLinear requires 2 or 3 inputs.");if(e.length===3&&e[1].dims===e[2].dims)throw new Error("x-scale and x-zero-point must have the same shape.");if(e.length===3&&e[0].dataType!==e[2].dataType)throw new Error("x and x-zero-point must have the same data type.");if(e[0].dataType===6&&e.length>2)throw new Error("In the case of dequantizing int32 there is no zero point.");if(e[1].dims.length!==0&&e[1].dims.length!==1&&e[1].dims.length!==e[0].dims.length)throw new Error("scale input must be a scalar, a 1D tensor, or have the same rank as the input tensor.");if(e.length>2){if(e[0].dataType!==e[2].dataType)throw new Error("x and x-zero-point must have the same data type.");if(e[1].dims.length!==e[2].dims.length)throw new Error("scale and zero-point inputs must have the same rank.");if(!e[1].dims.map((r,i)=>r===e[2].dims[i]).reduce((r,i)=>r&&i,!0))throw new Error("scale and zero-point inputs must have the same shape.")}if(t.blockSize>0){if(e[1].dims.length===0||e[1].dims.length===1&&e[1].dims[0]===1)throw new Error("blockSize must be set only for block quantization.");if(!e[1].dims.map((a,n)=>n===t.axis||a===e[0].dims[n]).reduce((a,n)=>a&&n,!0))throw new Error("For block qunatization, scale input shape to match the input shape except for the axis");if(e[1].dims.length!==e[0].dims.length)throw new Error("For block qunatization the scale input rank must be the same as the x rank.");let r=e[0].dims[t.axis],i=e[1].dims[t.axis];if(t.blockSize<Math.ceil(r/i)||t.blockSize>Math.ceil(r/(i-1)-1))throw new Error("blockSize must be with in the range [ceil(dI / Si), ceil(dI / (Si - 1) - 1)].")}},xd=(e,t)=>{let r=M.normalizeAxis(t.axis,e[0].dims.length),i=e[0].dataType,a=i===3,n=e[0].dims,s=e[1].dataType,o=M.size(n),u=i===3||i===2,l=u?[Math.ceil(M.size(e[0].dims)/4)]:e[0].dims,d=e[1].dims,p=e.length>2?e[2]:void 0,h=p?u?[Math.ceil(M.size(p.dims)/4)]:p.dims:void 0,f=d.length===0||d.length===1&&d[0]===1,m=f===!1&&d.length===1,w=A(o),$=f&&(!u||w===4),_=$?w:1,y=$&&!u?w:1,S=z("input",u?12:i,l.length,y),v=z("scale",s,d.length),E=p?z("zero_point",u?12:i,h.length):void 0,B=q("output",s,n.length,_),R=[S,v];E&&R.push(E);let U=[l,d];p&&U.push(h);let W=[{type:12,data:o/_},{type:12,data:r},{type:12,data:t.blockSize},...k(...U,n)],X=ke=>{let ae=[{name:"output_size",type:"u32"},{name:"axis",type:"u32"},{name:"block_size",type:"u32"}];return`
      ${ke.registerUniforms(ae).declareVariables(...R,B)}
      ${ke.mainStart()}
          ${ke.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
          let output_indices = ${B.offsetToIndices("global_idx")};

          // Set input x
          ${u?`
            let input = ${S.getByOffset("global_idx / 4")};
            let x_vec = ${a?"unpack4xI8(input)":"unpack4xU8(input)"};
            let x_value = ${_===1?"x_vec[global_idx % 4]":"x_vec"};`:`let x_value = ${S.getByOffset("global_idx")};`};

          // Set scale input
          ${f?`let scale_value= ${v.getByOffset("0")}`:m?`
            let scale_index = ${B.indicesGet("output_indices","uniforms.axis")};
            let scale_value= ${v.getByOffset("scale_index")};`:`
            var scale_indices: ${v.type.indices} = output_indices;
            let index = ${v.indicesGet("scale_indices","uniforms.axis")} / uniforms.block_size;
            ${v.indicesSet("scale_indices","uniforms.axis","index")};
            let scale_value= ${v.getByIndices("scale_indices")};`};

          // Set zero-point input
          ${E?f?u?`
                let zero_point_input = ${E.getByOffset("0")};
                let zero_point_vec =  ${a?"unpack4xI8(zero_point_input)":"unpack4xU8(zero_point_input)"};
                let zero_point_value= zero_point_vec[0]`:`let zero_point_value = ${E.getByOffset("0")}`:m?u?`
                let zero_point_index = ${B.indicesGet("output_indices","uniforms.axis")};
                let zero_point_input = ${E.getByOffset("zero_point_index / 4")};
                let zero_point_vec =  ${a?"unpack4xI8(zero_point_input)":"unpack4xU8(zero_point_input)"};
                let zero_point_value = zero_point_vec[zero_point_index % 4]`:`
                let zero_point_index = ${B.indicesGet("output_indices","uniforms.axis")};
                let zero_point_value = ${E.getByOffset("zero_point_index")};`:u?`
                let zero_point_offset = ${v.indicesToOffset("scale_indices")};
                let zero_point_input = ${E.getByOffset("zero_point_offset / 4")};
                let zero_point_vec = ${a?"unpack4xI8(zero_point_input)":"unpack4xU8(zero_point_input)"};
                let zero_point_value = zero_point_vec[zero_point_offset % 4];`:`let zero_point_value = ${E.getByIndices("scale_indices")};`:`let zero_point_value = ${u?a?"i32":"u32":S.type.value}(0);`};
      // Compute and write output
      ${B.setByOffset("global_idx",`${B.type.value}(x_value - zero_point_value) * scale_value`)};
      }`};return{name:"DequantizeLinear",shaderCache:{hint:t.cacheKey,inputDependencies:E?["rank","rank","rank"]:["rank","rank"]},getShaderSource:X,getRunData:()=>({outputs:[{dims:n,dataType:s}],dispatchGroup:{x:Math.ceil(o/_/64),y:1,z:1},programUniforms:W})}},Sd=(e,t)=>{vd(e.inputs,t),e.compute(xd(e.inputs,t))},Td=e=>g({axis:e.axis,blockSize:e.blockSize})}),Ed,kd,Id,jc=I(()=>{Ye(),ue(),Z(),Ed=(e,t,r)=>{let i=e===t,a=e<t&&r<0,n=e>t&&r>0;if(i||a||n)throw new Error("Range these inputs' contents are invalid.")},kd=(e,t,r,i)=>{let a=Math.abs(Math.ceil((t-e)/r)),n=[a],s=a,o=[{type:12,data:s},{type:i,data:e},{type:i,data:r},...k(n)],u=l=>{let d=q("output",i,n.length),p=d.type.value,h=[{name:"outputSize",type:"u32"},{name:"start",type:p},{name:"delta",type:p}];return`
        ${l.registerUniforms(h).declareVariables(d)}
        ${l.mainStart()}
        ${l.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}
        output[global_idx] = uniforms.start + ${p}(global_idx) * uniforms.delta;
      }`};return{name:"Range",shaderCache:{hint:`${i}`},getShaderSource:u,getRunData:()=>({outputs:[{dims:n,dataType:i}],dispatchGroup:{x:Math.ceil(s/64)},programUniforms:o})}},Id=e=>{let t=0,r=0,i=0;e.inputs[0].dataType===6?(t=e.inputs[0].getInt32Array()[0],r=e.inputs[1].getInt32Array()[0],i=e.inputs[2].getInt32Array()[0]):e.inputs[0].dataType===1&&(t=e.inputs[0].getFloat32Array()[0],r=e.inputs[1].getFloat32Array()[0],i=e.inputs[2].getFloat32Array()[0]),ie.webgpu.validateInputContent&&Ed(t,r,i),e.compute(kd(t,r,i,e.inputs[0].dataType),{inputs:[]})}}),Cd,zd,Ad,Od,Hc=I(()=>{ue(),oe(),b(),Z(),Cd=(e,t,r,i)=>{if(e!=="none"&&i!=="i32"&&i!=="u32"&&i!=="f32")throw new Error(`Input ${i} is not supported with reduction ${e}.`);let a=`{
                var oldValue = 0;
                loop {
                  let newValueF32 =`,n=`;
                  let newValue = bitcast<i32>(newValueF32);
                  let res = atomicCompareExchangeWeak(&${t}, oldValue, newValue);
                  if res.exchanged {
                    break;
                  }
                  oldValue = res.old_value;
                }
              }`;switch(e){case"none":return`${t}=${r};`;case"add":return i==="i32"||i==="u32"?`atomicAdd(&${t}, bitcast<${i}>(${r}));`:`
              ${a}bitcast<${i}>(oldValue) + (${r})${n}`;case"max":return i==="i32"||i==="u32"?`atomicMax(&${t}, bitcast<${i}>(${r}));`:`
                ${a}max(bitcast<f32>(oldValue), (${r}))${n}`;case"min":return i==="i32"||i==="u32"?`atomicMin(&${t}, bitcast<${i}>(${r}));`:`${a}min(bitcast<${i}>(oldValue), (${r}))${n}`;case"mul":return`${a}(bitcast<${i}>(oldValue) * (${r}))${n}`;default:throw new Error(`Reduction ${e} is not supported.`)}},zd=(e,t)=>{let r=e[0].dims,i=e[1].dims,a=r,n=1,s=Math.ceil(M.sizeToDimension(i,i.length-1)/n),o=i[i.length-1],u=M.sizeFromDimension(r,o),l=[{type:12,data:s},{type:12,data:o},{type:12,data:u},...k(e[1].dims,e[2].dims,a)],d=p=>{let h=z("indices",e[1].dataType,e[1].dims.length),f=z("updates",e[2].dataType,e[2].dims.length,n),m=t.reduction!=="none"&&t.reduction!==""?qe("output",e[0].dataType,a.length):q("output",e[0].dataType,a.length,n);return`
      ${p.registerUniform("output_size","u32").registerUniform("last_index_dimension","u32").registerUniform("num_updates_elements","u32").declareVariables(h,f,m)}
      ${p.mainStart()}
        ${p.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
  var data_offset = 0u;
  let indices_start = uniforms.last_index_dimension * global_idx;
  let indices_end = indices_start + uniforms.last_index_dimension;
  for (var i = indices_start; i < indices_end; i++) {
    var index = i32(indices[i].x);
    ${e[0].dims.length===1?`
    let element_count_dim = uniforms.output_strides;
    let dim_value = uniforms.output_shape;`:`
    let element_count_dim = uniforms.output_strides[i - indices_start];
    let dim_value = uniforms.output_shape[i - indices_start];`}
    if (index >= 0) {
      if (index >= i32(dim_value)) {
        index = i32(dim_value - 1);
      }
    } else {
      if (index < -i32(dim_value)) {
        index = 0;
      } else {
        index += i32(dim_value);
      }
    }
    data_offset += u32((u32(index) * element_count_dim));
  }

  for (var i = 0u; i < uniforms.num_updates_elements; i++) {
    let value = updates[uniforms.num_updates_elements * global_idx + i];
    ${Cd(t.reduction,"output[data_offset + i]","value",m.type.value)}
  }

      }`};return{name:"ScatterND",shaderCache:{hint:`${t.cacheKey}_${t.reduction}`,inputDependencies:["rank","rank"]},getRunData:()=>({outputs:[{dims:a,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(s/64)},programUniforms:l}),getShaderSource:d}},Ad=e=>g({reduction:e.reduction}),Od=(e,t)=>{e.compute(zd(e.inputs,t),{inputs:[e.inputs[1],e.inputs[2]],outputs:[]})}}),Rd,Bd,Md,Ln,Dd,Pd,Ud,Nd,Ld,Vd,qd,Fd,Vn,Wd,Gd,jd,Hd,Kd,Zd,Qd,Kc=I(()=>{ue(),oe(),b(),Z(),Rd=(e,t)=>{if(e.every(r=>r>0||(()=>{throw new Error("Resize requires scales input values to be positive")})),e.length>0){if(t.mode==="linear"){if(!(e.length===2||e.length===3||e.length===4&&e[0]===1&&e[1]===1||e.length===4&&e[0]===1&&e[3]===1||e.length===5&&e[0]===1&&e[1]===1))throw new Error(`For linear mode, Resize requires scales to be 2D, 3D, 4D with either two outermost or one innermost and
            one outermost scale values equal to 1, or 5D with two outermost scale values equal to 1`)}else if(t.mode==="cubic"&&!(e.length===2||e.length===4&&e[0]===1&&e[1]===1||e.length===4&&e[0]===1&&e[3]===1))throw new Error("Resize requires scales input size to be 2 or 4 for cubic mode")}},Bd=(e,t,r)=>{t.every(a=>a>=0&&a<r||(()=>{throw new Error("Resize requires axes input values to be positive and less than rank")}));let i=new Array(r).fill(1);return t.forEach((a,n)=>i[a]=e[n]),i},Md=(e,t,r,i,a,n)=>{let[s,o,u]=r>10?[1,2,3]:[-1,e.length>1?1:-1,-1],l=e[0].dims.length;if(s>0&&e.length>s&&e[s].dims.length>0)e[s].getFloat32Array().forEach(d=>n.push(d));else if(t.coordinateTransformMode==="tf_crop_and_resize")throw new Error("Resize requires RoI input to be specified when coordinateTransformMode is tfCropAndResize");if(o>0&&e.length>o&&e[o].dims.length===1&&e[o].dims[0]>0){if(e[o].getFloat32Array().forEach(d=>i.push(d)),i.length!==0&&i.length!==l&&r>=18&&i.length!==t.axes.length)throw new Error("Resize requires scales input size to be same as input rank or axes size for opset 18 and up");Rd(i,t),t.axes.length>0&&Bd(i,t.axes,l).forEach((d,p)=>i[p]=d)}if(u>0&&e.length>u&&e[u].dims.length===1&&e[u].dims[0]>0&&(e[u].getBigInt64Array().forEach(d=>a.push(Number(d))),a.length!==0&&a.length!==l&&r>=18&&a.length!==t.axes.length))throw new Error("Resize requires sizes input size to be same as input rank or axes size for opset 18 and up");if(t.axes.length>0){if(i.length!==0&&i.length!==t.axes.length)throw new Error('Resize requires "scales" input size to be of axes rank when axes attributes is specified');if(a.length!==0&&a.length!==t.axes.length)throw new Error('Resize requires "sizes" input size to be of rank axes rank when axes attributes is specified')}if(typeof i<"u"&&typeof a<"u"&&i.length>0&&a.length>l)throw new Error("Resize requires only of scales or sizes to be specified")},Ln=(e,t,r,i)=>`
  // The whole part and the fractional part are calculated separately due to inaccuracy of floating
  // point division. As an example, f32(21) / f32(7) may evaluate to 2.99... instead of 3, causing an
  // offset-by-one error later in floor().
  let big = (${e}) * (${t});
  let whole = ${i}(big / (${r}));
  let fract = ${i}(big % (${r})) / ${i}(${r});
  return whole + fract;
`,Dd=(e,t)=>`fn getOriginalCoordinateFromResizedCoordinate(xResized: u32, xScale: f32, lengthResized: u32,
     lengthOriginal: u32, roiStart: f32, roiEnd: f32) -> ${t} { `+(()=>{switch(e){case"asymmetric":return`
          if (xScale < 1.0 || floor(xScale) != xScale) {
            return ${t}(xResized) / ${t}(xScale);
          } else {
            ${Ln("xResized","lengthOriginal","lengthResized",t)}
          }
        `;case"pytorch_half_pixel":return`if (lengthResized > 1) {
                    return (${t}(xResized) + 0.5) / ${t}(xScale) - 0.5;
                  } else {
                    return 0.0;
                  }`;case"tf_half_pixel_for_nn":return`return (${t}(xResized) + 0.5) / ${t}(xScale);`;case"align_corners":return`if (lengthResized == 1) {
                    return 0.0;
                  } else {
                    ${Ln("xResized","lengthOriginal - 1","lengthResized - 1",t)}
                  }`;case"tf_crop_and_resize":return`if (lengthResized > 1) {
                    return ${t}(roiStart) * ${t}(lengthOriginal - 1) +
                        (${t}(xResized) * ${t}(roiEnd - roiStart) * ${t}(lengthOriginal - 1)) /
                        ${t}(lengthResized - 1);
                  } else {
                    return 0.5 * ${t}(roiStart + roiEnd) * ${t}(lengthOriginal - 1);
                  }`;case"half_pixel_symmetric":return`const outputWidth = ${t}xScale * ${t}(lengthResized);
                  const adjustment = ${t}(lengthResized) / outputWidth;
                  const center = ${t}(lengthOriginal) / 2;
                  const offset = center * (1 - adjustment);
                  return offset + ((${t}(xResized) + 0.5) / ${t}(xScale)) - 0.5;`;case"half_pixel":return`return ((${t}(xResized) + 0.5) / ${t}(xScale)) - 0.5;`;default:throw new Error(`Coordinate transform mode ${e} is not supported`)}})()+"}",Pd=(e,t,r)=>`fn getNearestPixelFromOriginal(xOriginal: ${r}, isDownSample: bool) -> ${r} {`+(()=>{switch(e){case"round_prefer_ceil":return"if (fract(xOriginal) == 0.5) {             return ceil(xOriginal);           } else {             return round(xOriginal);           }";case"floor":return"return floor(xOriginal);";case"ceil":return"return ceil(xOriginal);";case"round_prefer_floor":return"if (fract(xOriginal) == 0.5) {                     return floor(xOriginal);                   } else {                     return round(xOriginal);                   }";default:if(t<11)return"if (isDownSample)                     {                       return ceil(xOriginal);                     } else {                       return xOriginal;                     }";throw new Error(`Nearest mode ${e} is not supported`)}})()+"}",Ud=(e,t,r)=>{let i=new Array(r).fill(0).concat(new Array(r).fill(1)),a=e.length===0?i:e.slice();return t.length>0?(t.forEach((n,s)=>{i[n]=a[s],i[s+r]=a[t.length+s]}),i):a},Nd=(e,t,r,i)=>{let a=[];if(r.length>0)if(i.length>0){if(e.forEach(n=>a.push(n)),Math.max(...i)>e.length)throw new Error("axes is out of bound");i.forEach((n,s)=>a[n]=r[s])}else r.forEach(n=>a.push(n));else{if(t.length===0)throw new Error("Resize requires either scales or sizes.");a=e.map((n,s)=>Math.round(n*t[s]))}return a},Ld=(e,t,r)=>{let i=(()=>{switch(r.keepAspectRatioPolicy){case"not_larger":return r.axes.length>0?Math.min(...r.axes.map(n=>t[n]),Number.MAX_VALUE):Math.min(...t,Number.MAX_VALUE);case"not_smaller":return r.axes.length>0?Math.max(...r.axes.map(n=>t[n]),Number.MIN_VALUE):Math.max(...t,Number.MIN_VALUE);default:throw new Error(`Keep aspect ratio policy ${r.keepAspectRatioPolicy} is not supported`)}})();t.fill(1,0,t.length);let a=e.slice();return r.axes.length>0?(r.axes.forEach(n=>t[n]=i),r.axes.forEach(n=>a[n]=Math.round(e[n]*t[n]))):(t.fill(i,0,t.length),a.forEach((n,s)=>a[s]=Math.round(n*t[s]))),a},Vd=(e,t,r,i,a)=>`
    fn calculateOriginalIndicesFromOutputIndices(output_indices: ${e.type.indices}) -> array<${e.type.value}, ${r.length}> {
      var original_indices: array<${e.type.value}, ${r.length}>;
      for (var i:u32 = 0; i < ${r.length}; i++) {
        var output_index = ${e.indicesGet("output_indices","i")};
        var scale = ${D("uniforms.scales","i",i)};
        var roi_low = ${D("uniforms.roi","i",a)};
        var roi_hi = ${D("uniforms.roi",`i + ${t.length}`,a)};
        if (scale == 1.0) {
          original_indices[i] = ${e.type.value}(output_index);
        } else {
          var input_shape_i = ${D("uniforms.input_shape","i",t.length)};
          var output_shape_i = ${D("uniforms.output_shape","i",r.length)};
          original_indices[i] = getOriginalCoordinateFromResizedCoordinate(output_index, scale, output_shape_i,
                                                                           input_shape_i, roi_low, roi_hi);
        }
      }
      return original_indices;
    }`,qd=(e,t,r,i,a,n,s)=>`
    fn calculateInputIndicesFromOutputIndices(output_indices: ${t.type.indices}) -> ${e.type.indices} {
      var input_indices: ${e.type.indices};
      for (var i:u32 = 0; i < ${i.length}; i++) {
        var output_index = ${t.indicesGet("output_indices","i")};
        var input_index: u32;
        var scale = ${D("uniforms.scales","i",a)};
        if (scale == 1.0) {
          input_index = output_index;
        } else {
          var roi_low = ${D("uniforms.roi","i",n)};
          var roi_hi = ${D("uniforms.roi",`i + ${r.length}`,n)};
          var input_shape_i = ${D("uniforms.input_shape","i",r.length)};
          var output_shape_i = ${D("uniforms.output_shape","i",i.length)};
          var original_idx = getOriginalCoordinateFromResizedCoordinate(output_index, scale, output_shape_i,
                                                                        input_shape_i, roi_low, roi_hi);
          if (!${s} || (original_idx >= 0 && original_idx < ${t.type.value}(input_shape_i))) {
            if (original_idx < 0) {
              input_index = 0;
            } else if (original_idx > ${t.type.value}(input_shape_i - 1)) {
              input_index = input_shape_i - 1;
            } else {
              input_index = u32(getNearestPixelFromOriginal(original_idx, scale < 1));
            }
          } else {
            input_index = u32(original_idx);
          }
        }
        ${e.indicesSet("input_indices","i","input_index")}
      }
      return input_indices;
    }`,Fd=(e,t)=>`
    fn checkInputIndices(input_indices: ${e.type.indices}) -> bool {
      for (var i:u32 = 0; i < ${t.length}; i++) {
        var input_index = ${e.indicesGet("input_indices","i")};
        if (input_index < 0 || input_index >= ${D("uniforms.input_shape","i",t.length)}) {
          return false;
        }
      }
      return true;
    }`,Vn=(e,t,r,i)=>e.rank>i?`
    ${e.indicesSet("input_indices",t,"channel")};
    ${e.indicesSet("input_indices",r,"batch")};
`:"",Wd=(e,t,r,i,a)=>{let[n,s,o,u]=r.length===2?[-1,0,1,-1]:[0,2,3,1],l=e.type.value;return`
    fn getInputValue(batch: u32, channel: u32, row: u32, col: u32) -> ${l} {
      var input_indices: ${e.type.indices};
      ${e.indicesSet("input_indices",s,`max(0, min(row, ${r[s]} - 1))`)};
      ${e.indicesSet("input_indices",o,`max(0, min(col, ${r[o]} - 1))`)};
      ${Vn(e,u,n,2)}
      return ${e.getByIndices("input_indices")};
    }

    fn bilinearInterpolation(output_indices: ${t.type.indices}) -> ${l} {
      var originalIndices = calculateOriginalIndicesFromOutputIndices(output_indices);
      var row:${l} = originalIndices[${s}];
      var col:${l} = originalIndices[${o}];
      ${i?`if (row < 0 || row > (${r[s]} - 1) || col < 0 || col > (${r[o]} - 1)) {
        return ${a};
      }`:""};
      row = max(0, min(row, ${r[s]} - 1));
      col = max(0, min(col, ${r[o]} - 1));
      var row1: u32 = u32(row);
      var col1: u32 = u32(col);
      var row2: u32 = u32(row + 1);
      var col2: u32 = u32(col + 1);
      var channel: u32 = ${r.length>2?`u32(originalIndices[${u}])`:"0"};
      var batch: u32 =  ${r.length>2?`u32(originalIndices[${n}])`:"0"};
      var x11: ${l} = getInputValue(batch, channel, row1, col1);
      var x12: ${l} = getInputValue(batch, channel, row1, col2);
      var x21: ${l} = getInputValue(batch, channel, row2, col1);
      var x22: ${l} = getInputValue(batch, channel, row2, col2);
      var dx1: ${l} = abs(row - ${l}(row1));
      var dx2: ${l} = abs(${l}(row2) - row);
      var dy1: ${l} = abs(col - ${l}(col1));
      var dy2: ${l} = abs(${l}(col2) - col);
      if (row1 == row2) {
        dx1 = 0.5;
        dx2 = 0.5;
      }
      if (col1 == col2) {
        dy1 = 0.5;
        dy2 = 0.5;
      }
      return (x11 * dx2 * dy2 + x12 * dx2 * dy1 + x21 * dx1 * dy2 + x22 * dx1 * dy1);
    }`},Gd=(e,t,r,i,a,n,s,o,u,l)=>{let d=r.length===2,[p,h]=d?[0,1]:[2,3],f=e.type.value,m=w=>{let $=w===p?"row":"col";return`
      fn ${$}CubicInterpolation(input_indices: ${e.type.indices}, output_indices: ${t.type.indices}) -> ${f} {
        var output_index = ${t.indicesGet("output_indices",w)};
        var originalIdx: ${f} = getOriginalCoordinateFromResizedCoordinate(output_index, ${a[w]},
        ${i[w]}, ${r[w]}, ${n[w]}, ${n[w]} + ${r.length});
        var fractOriginalIdx: ${f} = originalIdx - floor(originalIdx);
        var coefs = getCubicInterpolationCoefs(fractOriginalIdx);

        if (${o} && (originalIdx < 0 || originalIdx > (${r[w]} - 1))) {
          return ${u};
        }
        var data: array<${f}, 4> = array<${f}, 4>(0.0, 0.0, 0.0, 0.0);
        for (var i: i32 = -1; i < 3; i++) {
          var ${$}: ${f} = originalIdx + ${f}(i);
          if (${$} < 0 || ${$} >= ${r[w]}) {
            ${l?`coefs[i + 1] = 0.0;
                        continue;`:o?`return ${u};`:`${$} = max(0, min(${$}, ${r[w]} - 1));`};
          }
        var input_indices_copy: ${e.type.indices} = input_indices;
          ${e.indicesSet("input_indices_copy",w,`u32(${$})`)};
          data[i + 1] = ${w===p?e.getByIndices("input_indices_copy"):"rowCubicInterpolation(input_indices_copy, output_indices)"};
        }
        return cubicInterpolation1D(data, coefs);
      }`};return`
    ${m(p)};
    ${m(h)};
  fn getCubicInterpolationCoefs(s: ${f}) -> array<${f}, 4> {
    var absS = abs(s);
    var coeffs: array<${f}, 4> = array<${f}, 4>(0.0, 0.0, 0.0, 0.0);
    var oneMinusAbsS: ${f} = 1.0 - absS;
    var twoMinusAbsS: ${f} = 2.0 - absS;
    var onePlusAbsS: ${f} = 1.0 + absS;
    coeffs[0] = ((${s} * onePlusAbsS - 5 * ${s}) * onePlusAbsS + 8 * ${s}) * onePlusAbsS - 4 * ${s};
    coeffs[1] = ((${s} + 2) * absS - (${s} + 3)) * absS * absS + 1;
    coeffs[2] = ((${s} + 2) * oneMinusAbsS - (${s} + 3)) * oneMinusAbsS * oneMinusAbsS + 1;
    coeffs[3] = ((${s} * twoMinusAbsS - 5 * ${s}) * twoMinusAbsS + 8 * ${s}) * twoMinusAbsS - 4 * ${s};
    return coeffs;
  }

  fn cubicInterpolation1D(x: array<${f}, 4>, coefs: array<${f}, 4>) -> ${f} {
    var coefsSum: ${f} = coefs[0] + coefs[1] + coefs[2] + coefs[3];
    return (x[0] * coefs[0] + x[1] * coefs[1]+ x[2] * coefs[2]+ x[3] * coefs[3]) / coefsSum;
  }

  fn bicubicInterpolation(output_indices: ${t.type.indices}) -> ${f} {
    var input_indices: ${e.type.indices} = output_indices;
    return colCubicInterpolation(input_indices, output_indices);
  }
    `},jd=(e,t,r,i,a)=>{let[n,s,o,u,l]=r.length===3?[-1,0,1,2,-1]:[0,2,3,4,1],d=e.type.value;return`
    fn getInputValue(batch: u32, channel: u32, depth:u32, height: u32, width: u32) -> ${d} {
      var input_indices: ${e.type.indices};
      ${e.indicesSet("input_indices",s,`max(0, min(depth, ${r[s]} - 1))`)};
      ${e.indicesSet("input_indices",o,`max(0, min(height, ${r[o]} - 1))`)};
      ${e.indicesSet("input_indices",u,`max(0, min(width, ${r[u]} - 1))`)};
      ${Vn(e,l,n,3)}
      return ${e.getByIndices("input_indices")};
    }

    fn trilinearInterpolation(output_indices: ${t.type.indices}) -> ${d} {
      var originalIndices = calculateOriginalIndicesFromOutputIndices(output_indices);
      var depth:${d} = originalIndices[${s}];
      var height:${d} = originalIndices[${o}];
      var width:${d} = originalIndices[${u}];
      ${i?`if (depth < 0 || depth > (${r[s]} - 1) || height < 0 || height > (${r[o]} - 1) || width < 0 || (width > ${r[u]} - 1)) {
      return ${a};
        }`:""};

    depth = max(0, min(depth, ${r[s]} - 1));
      height = max(0, min(height, ${r[o]} - 1));
      width = max(0, min(width, ${r[u]} - 1));
      var depth1: u32 = u32(depth);
      var height1: u32 = u32(height);
      var width1: u32 = u32(width);
      var depth2: u32 = u32(depth + 1);
      var height2: u32 = u32(height + 1);
      var width2: u32 = u32(width + 1);
      var channel: u32 = ${r.length>3?`u32(originalIndices[${l}])`:"0"};
      var batch: u32 =  ${r.length>3?`u32(originalIndices[${n}])`:"0"};

      var x111: ${d} = getInputValue(batch, channel, depth1, height1, width1);
      var x112: ${d} = getInputValue(batch, channel, depth1, height1, width2);
      var x121: ${d} = getInputValue(batch, channel, depth1, height2, width1);
      var x122: ${d} = getInputValue(batch, channel, depth1, height2, width2);
      var x211: ${d} = getInputValue(batch, channel, depth2, height1, width1);
      var x212: ${d} = getInputValue(batch, channel, depth2, height1, width2);
      var x221: ${d} = getInputValue(batch, channel, depth2, height2, width1);
      var x222: ${d} = getInputValue(batch, channel, depth2, height2, width2);
      var dx1: ${d} = abs(depth - ${d}(depth1));
      var dx2: ${d} = abs(${d}(depth2) - depth);
      var dy1: ${d} = abs(height - ${d}(height1));
      var dy2: ${d} = abs(${d}(height2) - height);
      var dz1: ${d} = abs(width - ${d}(width1));
      var dz2: ${d} = abs(${d}(width2) - width);
      if (depth1 == depth2) {
        dx1 = 0.5;
        dx2 = 0.5;
      }
      if (height1 == height2) {
        dy1 = 0.5;
        dy2 = 0.5;
      }
      if (width1 == width2) {
        dz1 = 0.5;
        dz2 = 0.5;
      }
      return (x111 * dx2 * dy2 * dz2 + x112 * dx2 * dy2 * dz1 + x121 * dx2 * dy1 *dz2 + x122 * dx2 * dy1 * dz1 +
              x211 * dx1 * dy2 * dz2 + x212 * dx1 * dy2 * dz1 + x221 * dx1 * dy1 *dz2 + x222 * dx1 * dy1 * dz1);
    }`},Hd=(e,t,r,i,a,n)=>{let s=e.dims,o=Ud(n,t.axes,s.length),u=Nd(s,i,a,t.axes),l=i.slice();i.length===0&&(l=s.map((y,S)=>y===0?1:u[S]/y),t.keepAspectRatioPolicy!=="stretch"&&(u=Ld(s,l,t)));let d=q("output",e.dataType,u.length),p=z("input",e.dataType,s.length),h=M.size(u),f=s.length===u.length&&s.every((y,S)=>y===u[S]),m=t.coordinateTransformMode==="tf_crop_and_resize",w=t.extrapolationValue,$=p.type.value,_=y=>`
      ${f?"":`
      ${Dd(t.coordinateTransformMode,$)};
      ${(()=>{switch(t.mode){case"nearest":return`
              ${Fd(p,s)};
              ${Pd(t.nearestMode,r,$)};
              ${qd(p,d,s,u,l.length,o.length,m)};
              `;case"linear":return`
              ${Vd(d,s,u,l.length,o.length)};
              ${(()=>{if(s.length===2||s.length===4)return`${Wd(p,d,s,m,w)}`;if(s.length===3||s.length===5)return`${jd(p,d,s,m,w)}`;throw Error("Linear mode only supports input dims 2, 3, 4 and 5 are supported in linear mode.")})()};
            `;case"cubic":return`
            ${(()=>{if(s.length===2||s.length===4)return`${Gd(p,d,s,u,l,o,t.cubicCoeffA,m,t.extrapolationValue,t.excludeOutside)}`;throw Error("Cubic mode only supports input dims 2 and 4 are supported in linear mode.")})()};
            `;default:throw Error("Invalid resize mode")}})()};
      `}
      ${y.registerUniform("output_size","u32").registerUniform("scales","f32",l.length).registerUniform("roi","f32",o.length).declareVariables(p,d)}
      ${y.mainStart()}
        ${y.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
        ${f?"output[global_idx] = input[global_idx];":`
        let output_indices = ${d.offsetToIndices("global_idx")};
        var input_indices: ${p.type.indices};
        ${(()=>{switch(t.mode){case"nearest":return`input_indices = calculateInputIndicesFromOutputIndices(output_indices);
                if (checkInputIndices(input_indices)) {
                  output[global_idx] = ${p.getByIndices("input_indices")};
                } else {
                  output[global_idx] = ${t.extrapolationValue};
                }`;case"linear":return`output[global_idx] = ${s.length===2||s.length===4?"bilinearInterpolation":"trilinearInterpolation"}(output_indices);`;case"cubic":return"output[global_idx] = bicubicInterpolation(output_indices);";default:throw Error(`Unsupported resize mode: ${t.mode}`)}})()};
`}
      }`;return{name:"Resize",shaderCache:{hint:`${t.cacheKey}|${r}|${l.length>0?t.mode==="cubic"?l:l.length:""}|${a.length>0?a:""}|${o.length>0?o:""}|${f}|${t.mode==="nearest"?s.length:s}`,inputDependencies:["rank"]},getShaderSource:_,getRunData:()=>({outputs:[{dims:u,dataType:e.dataType}],dispatchGroup:{x:Math.ceil(h/64)},programUniforms:[{type:12,data:h},{type:1,data:l},{type:1,data:o},...k(s,u)]})}},Kd=e=>{let t=e.customDataBuffer;return new Uint32Array(t,t.byteOffset,1)[0]},Zd=(e,t)=>{let r=[],i=[],a=[],n=Kd(e);if(t.antialias!==0)throw Error("Only default value (0) for Antialias attribute is supported");Md(e.inputs,t,n,r,i,a),e.compute(Hd(e.inputs[0],t,n,r,i,a),{inputs:[0]})},Qd=e=>{let t=e.antialias,r=e.axes,i=e.coordinateTransformMode,a=e.cubicCoeffA,n=e.excludeOutside!==0,s=e.extrapolationValue,o=e.keepAspectRatioPolicy,u=e.mode,l=e.nearestMode===""?"simple":e.nearestMode;return g({antialias:t,axes:r,coordinateTransformMode:i,cubicCoeffA:a,excludeOutside:n,extrapolationValue:s,keepAspectRatioPolicy:o,mode:u,nearestMode:l})}}),Xd,Yd,Jd,Zc=I(()=>{ue(),oe(),Z(),Xd=e=>{if(!e||e.length<3)throw new Error("layerNorm requires at least 3 inputs.");let t=e[0],r=e[1],i=e[2];if(t.dataType!==r.dataType||t.dataType!==i.dataType)throw new Error("All inputs must have the same data type");if(t.dims.length!==3&&t.dims.length!==2)throw new Error("Input must be 2D or 3D");if(r.dims.length!==3&&r.dims.length!==2)throw new Error("Skip must be 2D or 3D");let a=t.dims[t.dims.length-1],n=t.dims[t.dims.length-2];if(r.dims[r.dims.length-1]!==a)throw new Error("Skip must have the same hidden size as input");if(r.dims[r.dims.length-2]!==n)throw new Error("Skip must have the same sequence length as input");if(i.dims.length!==1)throw new Error("Gamma must be 1D");if(i.dims[i.dims.length-1]!==a)throw new Error("Gamma must have the same hidden size as input");if(e.length>3){let s=e[3];if(s.dims.length!==1)throw new Error("Beta must be 1D");if(s.dims[s.dims.length-1]!==a)throw new Error("Beta must have the same hidden size as input")}if(e.length>4){let s=e[4];if(s.dims.length!==1)throw new Error("Bias must be 1D");if(s.dims[s.dims.length-1]!==a)throw new Error("Bias must have the same hidden size as input")}},Yd=(e,t,r,i)=>{let a=t.simplified,n=e[0].dims,s=M.size(n),o=n,u=s,l=n.slice(-1)[0],d=i?n.slice(0,-1).concat(1):[],p=!a&&e.length>3,h=e.length>4,f=i&&r>1,m=i&&r>2,w=r>3,$=64,_=A(l),y=[{type:12,data:u},{type:12,data:_},{type:12,data:l},{type:1,data:t.epsilon}],S=E=>{let B=[{name:"output_size",type:"u32"},{name:"components",type:"u32"},{name:"hidden_size",type:"u32"},{name:"epsilon",type:"f32"}],R=[z("x",e[0].dataType,e[0].dims,_),z("skip",e[1].dataType,e[1].dims,_),z("gamma",e[2].dataType,e[2].dims,_)];p&&R.push(z("beta",e[3].dataType,e[3].dims,_)),h&&R.push(z("bias",e[4].dataType,e[4].dims,_)),R.push(q("output",e[0].dataType,o,_)),f&&R.push(q("mean_output",1,d)),m&&R.push(q("inv_std_output",1,d)),w&&R.push(q("input_skip_bias_sum",e[0].dataType,o,_));let U=O(e[0].dataType),W=O(1,_);return`

      ${E.registerUniforms(B).declareVariables(...R)}
      var<workgroup> sum_shared : array<${W}, ${$}>;
      var<workgroup> sum_squared_shared : array<${W}, ${$}>;

      ${E.mainStart([$,1,1])}
        let ix = local_id.x;
        let iy = global_id.x / ${$};

        let hidden_size_vectorized: u32 = uniforms.hidden_size / uniforms.components;
        var stride = hidden_size_vectorized / ${$};
        let offset = ix * stride + iy * hidden_size_vectorized;
        let offset1d = stride * ix;
        if (ix == ${$-1}) {
          stride = hidden_size_vectorized - stride * ix;
        }
        for (var i: u32 = 0; i < stride; i++) {
          let skip_value = skip[offset + i];
          let bias_value = ${h?"bias[offset1d + i]":U+"(0.0)"};
          let input_value = x[offset + i];
          let value = input_value + skip_value + bias_value;
          ${w?"input_skip_bias_sum[offset + i] = value;":""}
          output[offset + i] = value;
          let f32_value = ${V(U,_,"value")};
          sum_shared[ix] += f32_value;
          sum_squared_shared[ix] += f32_value * f32_value;
        }
        workgroupBarrier();

        var reduce_size : u32 = ${$};
        for (var curr_size = reduce_size >> 1;  curr_size > 0; curr_size = reduce_size >> 1) {
          reduce_size = curr_size + (reduce_size & 1);
          if (ix < curr_size) {
            sum_shared[ix] += sum_shared[ix + reduce_size];
            sum_squared_shared[ix] += sum_squared_shared[ix + reduce_size];
          }
          workgroupBarrier();
        }

        let sum = sum_shared[0];
        let square_sum = sum_squared_shared[0];
        let mean = ${P("sum",_)} / f32(uniforms.hidden_size);
        let inv_std_dev = inverseSqrt(${P("square_sum",_)} / f32(uniforms.hidden_size) ${a?"":"- mean * mean"} + uniforms.epsilon);
        ${f?"mean_output[global_idx] = mean;":""}
        ${m?"inv_std_output[global_idx] = inv_std_dev;":""}

        for (var i: u32 = 0; i < stride; i++) {
          output[offset + i] = (output[offset + i] ${a?"":`- ${U}(mean)`}) *
            ${U}(inv_std_dev) * gamma[offset1d + i]
            ${p?"+ beta[offset1d + i]":""};
        }
      }`},v=[{dims:o,dataType:e[0].dataType}];return r>1&&v.push({dims:d,dataType:1}),r>2&&v.push({dims:d,dataType:1}),r>3&&v.push({dims:n,dataType:e[0].dataType}),{name:"SkipLayerNormalization",shaderCache:{hint:`${_};${f};${m};${w}`,inputDependencies:e.map((E,B)=>"type")},getShaderSource:S,getRunData:()=>({outputs:v,dispatchGroup:{x:Math.ceil(u/l)},programUniforms:y})}},Jd=(e,t)=>{Xd(e.inputs);let r=[0];e.outputCount>1&&r.push(-3),e.outputCount>2&&r.push(-3),e.outputCount>3&&r.push(3),e.compute(Yd(e.inputs,t,e.outputCount,!1),{outputs:r})}}),ep,sa,tp,qn,rp,ip,ap,np,Qc=I(()=>{ue(),oe(),b(),Z(),ep=(e,t)=>{if(!e||e.length<1)throw new Error("too few inputs");if(t.axes.length!==0){if(t.axes.length!==t.starts.length||t.axes.length!==t.ends.length)throw new Error("axes, starts and ends must have the same length")}else if(t.starts.length!==t.ends.length)throw new Error("starts and ends must have the same length");e.slice(1).forEach((r,i)=>{if(e[i+1].dataType!==6&&e[i+1].dataType!==7)throw new Error(`Input ${i} must be an array of int32 or int64`)})},sa=(e,t)=>{let r=[];if(e.length>t)if(e[t].dataType===7)e[t].getBigInt64Array().forEach(i=>r.push(Number(i)));else if(e[t].dataType===6)e[t].getInt32Array().forEach(i=>r.push(Number(i)));else throw new Error(`Input ${t} must be an array of int32 or int64`);return r},tp=(e,t)=>{if(e.length>1){let r=sa(e,1),i=sa(e,2),a=sa(e,3);return a.length===0&&(a=[...Array(e[0].dims.length).keys()]),g({starts:r,ends:i,axes:a})}else return t},qn=(e,t,r,i,a)=>{let n=e;return e<0&&(n+=r[i[t]]),a[t]<0?Math.max(0,Math.min(n,r[i[t]]-1)):Math.max(0,Math.min(n,r[i[t]]))},rp=(e,t,r)=>`fn calculateInputIndices(output_indices: ${t.type.indices}) -> ${e.type.indices} {
          var input_indices: ${e.type.indices};
          var carry = 0u;
          for (var i = ${r.length-1}; i >= 0; i--) {
            let input_shape_i = ${D("uniforms.input_shape","i",r.length)};
            let steps_i = ${D("uniforms.steps","i",r.length)};
            let signs_i = ${D("uniforms.signs","i",r.length)};
            let starts_i = ${D("uniforms.starts","i",r.length)};
            var output_index = ${t.indicesGet("output_indices","i")};
            var input_index = output_index * steps_i + starts_i + carry;
            carry = input_index / input_shape_i;
            input_index = input_index % input_shape_i;
            if (signs_i < 0) {
              input_index = input_shape_i - input_index - 1u + starts_i;
            }
            ${e.indicesSet("input_indices","i","input_index")};
          }
          return input_indices;
      }`,ip=(e,t)=>{let r=e[0].dims,i=M.size(r),a=t.axes.length>0?M.normalizeAxes(t.axes,r.length):[...Array(r.length).keys()],n=sa(e,4);n.forEach(_=>_!==0||(()=>{throw new Error("step cannot be 0")})),n.length===0&&(n=Array(a.length).fill(1));let s=t.starts.map((_,y)=>qn(_,y,r,a,n)),o=t.ends.map((_,y)=>qn(_,y,r,a,n));if(a.length!==s.length||a.length!==o.length)throw new Error("start, ends and axes should have the same number of elements");if(a.length!==r.length)for(let _=0;_<r.length;++_)a.includes(_)||(s.splice(_,0,0),o.splice(_,0,r[_]),n.splice(_,0,1));let u=n.map(_=>Math.sign(_));n.forEach((_,y,S)=>{if(_<0){let v=(o[y]-s[y])/_,E=s[y],B=E+v*n[y];s[y]=B,o[y]=E,S[y]=-_}});let l=r.slice(0);a.forEach((_,y)=>{l[_]=Math.ceil((o[_]-s[_])/n[_])});let d={dims:l,dataType:e[0].dataType},p=q("output",e[0].dataType,l.length),h=z("input",e[0].dataType,e[0].dims.length),f=M.size(l),m=[{name:"outputSize",type:"u32"},{name:"starts",type:"u32",length:s.length},{name:"signs",type:"i32",length:u.length},{name:"steps",type:"u32",length:n.length}],w=[{type:12,data:f},{type:12,data:s},{type:6,data:u},{type:12,data:n},...k(e[0].dims,l)],$=_=>`
      ${_.registerUniforms(m).declareVariables(h,p)}
        ${rp(h,p,r)}
        ${_.mainStart()}
          ${_.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.outputSize")}
          let output_indices = ${p.offsetToIndices("global_idx")};
          let input_indices = calculateInputIndices(output_indices);
          ${p.setByOffset("global_idx",h.getByIndices("input_indices"))}
      }`;return{name:"Slice",shaderCache:{hint:`${u.length}_${s.length}_${n.length}`,inputDependencies:["rank"]},getShaderSource:$,getRunData:()=>({outputs:[d],dispatchGroup:{x:Math.ceil(i/64)},programUniforms:w})}},ap=(e,t)=>{ep(e.inputs,t);let r=tp(e.inputs,t);e.compute(ip(e.inputs,r),{inputs:[0]})},np=e=>{let t=e.starts,r=e.ends,i=e.axes;return g({starts:t,ends:r,axes:i})}}),sp,op,up,lp,Xc=I(()=>{ue(),oe(),b(),Ee(),Z(),sp=e=>{if(!e||e.length!==1)throw new Error("Softmax op requires 1 input.")},op=(e,t)=>{let r=e.inputs[0],i=r.dims,a=M.size(i),n=i.length,s=M.normalizeAxis(t.axis,n),o=s<i.length-1,u,l=[];o?(l=Array.from({length:n},(R,U)=>U),l[s]=n-1,l[n-1]=s,u=e.compute(We(r,l),{inputs:[r],outputs:[-1]})[0]):u=r;let d=u.dims,p=d[n-1],h=a/p,f=A(p),m=p/f,w=64;h===1&&(w=256);let $=(R,U)=>U===4?`max(max(${R}.x, ${R}.y), max(${R}.z, ${R}.w))`:U===2?`max(${R}.x, ${R}.y)`:U===3?`max(max(${R}.x, ${R}.y), ${R}.z)`:R,_=z("x",u.dataType,u.dims,f),y=q("result",u.dataType,u.dims,f),S=_.type.value,v=O(u.dataType)==="f32"?`var threadMax = ${S}(-3.4028234663852886e+38f);`:`var threadMax = ${S}(-65504.0h);`,E=R=>`
      var<workgroup> rowMaxShared : ${S};
      var<workgroup> rowSumShared : ${S};
      var<workgroup> threadShared : array<${S}, ${w}>;

      fn getValue(row: i32, col: i32, row_stride: i32) -> ${S} {
        let index = row * row_stride + col;
        return x[index];
      }

      fn setValue(row: i32, col: i32, row_stride: i32, value: ${S}) {
        let index = row * row_stride + col;
        result[index] = value;
      }
      ${R.registerUniform("packedCols","i32").declareVariables(_,y)}
      ${R.mainStart(w)}
        let gindex = i32(global_idx);
        let lindex = i32(local_idx);
        const wg = ${w};
        let row = gindex / wg;
        let cols = uniforms.packedCols;
        let row_stride : i32 = uniforms.packedCols;

        // find the rows max
        ${v}
        for (var col = lindex; col < cols; col += wg) {
          let value = getValue(row, col, row_stride);
          threadMax = max(threadMax, value);
        }
        if (lindex < cols) {
          threadShared[lindex] = threadMax;
        }
        workgroupBarrier();

        var reduceSize = min(cols, wg);
        for (var currSize = reduceSize >> 1;  currSize > 0; currSize = reduceSize >> 1) {
          reduceSize = currSize + (reduceSize & 1);
          if (lindex < currSize) {
            threadShared[lindex] = max(threadShared[lindex], threadShared[lindex + reduceSize]);
          }
          workgroupBarrier();
        }
        if (lindex == 0) {
          rowMaxShared = ${S}(${$("threadShared[0]",f)});
        }
        workgroupBarrier();

        // find the rows sum
        var threadSum = ${S}(0.0);
        for (var col = lindex; col < cols; col += wg) {
          let subExp = exp(getValue(row, col, row_stride) - rowMaxShared);
          threadSum += subExp;
        }
        threadShared[lindex] = threadSum;
        workgroupBarrier();

        for (var currSize = wg >> 1;  currSize > 0; currSize = currSize >> 1) {
          if (lindex < currSize) {
            threadShared[lindex] = threadShared[lindex] + threadShared[lindex + currSize];
          }
          workgroupBarrier();
        }
        if (lindex == 0) {
          rowSumShared = ${S}(${P("threadShared[0]",f)});
        }
        workgroupBarrier();

        // calculate final value for each element in the row
        for (var col = lindex; col < cols; col += wg) {
          var value = exp(getValue(row, col, row_stride) - rowMaxShared) / rowSumShared;
          // max operation protects against NaN since all values should be >=0
          value = max(value, ${S}(0.0));
          setValue(row, col, row_stride, value);
        }
      }`,B=e.compute({name:"Softmax",shaderCache:{hint:`${f};${w}`,inputDependencies:["type"]},getRunData:()=>({outputs:[{dims:d,dataType:u.dataType}],dispatchGroup:{x:h},programUniforms:[{type:6,data:m}]}),getShaderSource:E},{inputs:[u],outputs:[o?-1:0]})[0];o&&e.compute(We(B,l),{inputs:[B]})},up=(e,t)=>{sp(e.inputs),op(e,t)},lp=e=>g({axis:e.axis})}),Fn,dp,pp,cp,hp,Yc=I(()=>{ue(),oe(),Z(),Fn=e=>Array.from(e.getBigInt64Array(),Number),dp=e=>{if(!e||e.length!==2)throw new Error("Tile requires 2 inputs.");if(e[0].dataType!==1&&e[0].dataType!==10&&e[0].dataType!==6&&e[0].dataType!==12)throw new Error("Tile only support float, float16, int32, and uint32 data types");if(e[1].dataType!==7)throw new Error("Tile `repeats` input should be of int64 data type");if(e[1].dims.length!==1)throw new Error("Tile `repeats` input should be 1-D");if(Fn(e[1]).length!==e[0].dims.length)throw new Error("Tile `repeats` input should have same number of elements as rank of input data tensor")},pp=(e,t)=>{let r=[];for(let i=0;i<e.length;++i)r.push(e[i]*t[i]);return r},cp=(e,t)=>{let r=e[0].dims,i=t??Fn(e[1]),a=pp(r,i),n=M.size(a),s=e[0].dataType,o=z("input",s,r.length),u=q("output",s,a.length),l=d=>`
      const inputShape = ${o.indices(...r)};
      ${d.registerUniform("output_size","u32").declareVariables(o,u)}
      ${d.mainStart()}
      ${d.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.output_size")}
      let output_indices = ${u.offsetToIndices("global_idx")};
      var input_indices: ${o.type.indices};
      for (var i = 0; i < ${r.length}; i++) {
        let input_dim_i = ${o.indicesGet("uniforms.input_shape","i")};
        let input_dim_value = ${u.indicesGet("output_indices","i")}  % input_dim_i;

        ${o.indicesSet("input_indices","i","input_dim_value")}
      }
      ${u.setByOffset("global_idx",o.getByIndices("input_indices"))}
    }`;return{name:"Tile",shaderCache:{hint:`${i}`,inputDependencies:["rank"]},getRunData:()=>({outputs:[{dims:a,dataType:e[0].dataType}],dispatchGroup:{x:Math.ceil(n/64)},programUniforms:[{type:12,data:n},...k(e[0].dims,a)]}),getShaderSource:l}},hp=e=>{dp(e.inputs),e.compute(cp(e.inputs),{inputs:[0]})}}),fp,mp,gp,Jc=I(()=>{ue(),oe(),Z(),fp=(e,t,r,i,a)=>{let n=q("output_data",a,r.length,4),s=z("a_data",t[1].dataType,t[1].dims.length,4),o=z("b_data",t[2].dataType,t[2].dims.length,4),u=z("c_data",t[0].dataType,t[0].dims.length,4),l,d=(p,h,f)=>`select(${h}, ${p}, ${f})`;if(!i)l=n.setByOffset("global_idx",d(s.getByOffset("global_idx"),o.getByOffset("global_idx"),u.getByOffset("global_idx")));else{let p=(h,f,m="")=>{let w=`a_data[index_a${f}][component_a${f}]`,$=`b_data[index_b${f}][component_b${f}]`,_=`bool(c_data[index_c${f}] & (0xffu << (component_c${f} * 8)))`;return`
            let output_indices${f} = ${n.offsetToIndices(`global_idx * 4u + ${f}u`)};
            let offset_a${f} = ${s.broadcastedIndicesToOffset(`output_indices${f}`,n)};
            let offset_b${f} = ${o.broadcastedIndicesToOffset(`output_indices${f}`,n)};
            let offset_c${f} = ${u.broadcastedIndicesToOffset(`output_indices${f}`,n)};
            let index_a${f} = offset_a${f} / 4u;
            let index_b${f} = offset_b${f} / 4u;
            let index_c${f} = offset_c${f} / 4u;
            let component_a${f} = offset_a${f} % 4u;
            let component_b${f} = offset_b${f} % 4u;
            let component_c${f} = offset_c${f} % 4u;
            ${h}[${f}] = ${m}(${d(w,$,_)});
          `};a===9?l=`
            var data = vec4<u32>(0);
            ${p("data",0,"u32")}
            ${p("data",1,"u32")}
            ${p("data",2,"u32")}
            ${p("data",3,"u32")}
            output_data[global_idx] = dot(vec4<u32>(0x1, 0x100, 0x10000, 0x1000000), vec4<u32>(data));`:l=`
            ${p("output_data[global_idx]",0)}
            ${p("output_data[global_idx]",1)}
            ${p("output_data[global_idx]",2)}
            ${p("output_data[global_idx]",3)}
          `}return`
        ${e.registerUniform("vec_size","u32").declareVariables(u,s,o,n)}
        ${e.mainStart()}
        ${e.guardAgainstOutOfBoundsWorkgroupSizes("uniforms.vec_size")}
        ${l}
      }`},mp=e=>{let t=e[1].dims,r=e[2].dims,i=e[0].dims,a=e[1].dataType,n=!(M.areEqual(t,r)&&M.areEqual(r,i)),s=t,o=M.size(t);if(n){let l=Lt.calcShape(Lt.calcShape(t,r,!1),i,!1);if(!l)throw new Error("Can't perform where op on the given tensors");s=l,o=M.size(s)}let u=Math.ceil(o/4);return{name:"Where",shaderCache:{inputDependencies:["rank","rank","rank"]},getShaderSource:l=>fp(l,e,s,n,a),getRunData:()=>({outputs:[{dims:s,dataType:a}],dispatchGroup:{x:Math.ceil(o/64/4)},programUniforms:[{type:12,data:u},...k(i,t,r,s)]})}},gp=e=>{e.compute(mp(e.inputs))}}),yp,eh=I(()=>{fc(),nn(),mc(),gc(),yc(),wc(),_c(),Sc(),Ec(),kc(),Ic(),Cc(),zc(),Ac(),Oc(),Rc(),Bc(),Mc(),Dc(),Pc(),Uc(),Nc(),Lc(),Vc(),qc(),Cl(),Fc(),Wc(),Gc(),jc(),Hc(),tn(),Kc(),Nl(),Zc(),Qc(),Xc(),Dl(),Yc(),Ee(),ln(),Jc(),yp=new Map([["Abs",[Qs]],["Acos",[Xs]],["Acosh",[Ys]],["Add",[Lo]],["ArgMax",[Ms,an]],["ArgMin",[Bs,an]],["Asin",[Js]],["Asinh",[eo]],["Atan",[to]],["Atanh",[ro]],["Attention",[Vs]],["AveragePool",[md,fd]],["BatchNormalization",[Gs]],["BiasAdd",[Ks]],["BiasSplitGelu",[Po]],["Cast",[ao,io]],["Ceil",[oo]],["Clip",[so]],["Concat",[eu,tu]],["Conv",[vn,bn]],["ConvTranspose",[Iu,Tu]],["Cos",[uo]],["Cosh",[lo]],["CumSum",[zu,Au]],["DepthToSpace",[Mu,Du]],["DequantizeLinear",[Sd,Td]],["Div",[Vo]],["Einsum",[qu,Fu]],["Elu",[po,ea]],["Equal",[qo]],["Erf",[co]],["Exp",[ho]],["Expand",[Hu]],["FastGelu",[Zu]],["Floor",[fo]],["FusedConv",[vn,bn]],["Gather",[Ju,Yu]],["GatherElements",[dl,ll]],["GatherBlockQuantized",[nl,sl]],["GatherND",[tl,rl]],["Gelu",[mo]],["Gemm",[fl,hl]],["GlobalAveragePool",[yd,gd]],["GlobalMaxPool",[$d,bd]],["Greater",[jo]],["GreaterOrEqual",[Ko]],["GridSample",[xl,Sl]],["GroupQueryAttention",[Fl]],["HardSigmoid",[xo,vo]],["InstanceNormalization",[jl]],["LayerNormalization",[Zl]],["LeakyRelu",[go,ea]],["Less",[Ho]],["LessOrEqual",[Zo]],["Log",[Ao]],["MatMul",[Xl]],["MatMulNBits",[td,rd]],["MaxPool",[wd,_d]],["Mul",[Fo]],["MultiHeadAttention",[Il,El]],["Neg",[wo]],["Not",[yo]],["Pad",[pd]],["Pow",[Wo]],["QuickGelu",[Bo,ea]],["Range",[Id]],["Reciprocal",[_o]],["ReduceMin",[Cs]],["ReduceMean",[Ss]],["ReduceMax",[Is]],["ReduceSum",[As]],["ReduceProd",[zs]],["ReduceL1",[Ts]],["ReduceL2",[Es]],["ReduceLogSum",[Rs]],["ReduceLogSumExp",[ks]],["ReduceSumSquare",[Os]],["Relu",[bo]],["Resize",[Zd,Qd]],["RotaryEmbedding",[Ul]],["ScatterND",[Od,Ad]],["Sigmoid",[$o]],["Sin",[So]],["Sinh",[To]],["Slice",[ap,np]],["SkipLayerNormalization",[Jd]],["Split",[Bl,Ml]],["Sqrt",[Eo]],["Softmax",[up,lp]],["Sub",[Go]],["Tan",[ko]],["Tanh",[Io]],["ThresholdedRelu",[zo,ea]],["Tile",[hp]],["Transpose",[bt,Xi]],["Where",[gp]]])}),wp,th=I(()=>{Ye(),yt(),Z(),wp=class{constructor(e){this.backend=e,this.repo=new Map,this.attributesBound=!1}getArtifact(e){return this.repo.get(e)}setArtifact(e,t){this.repo.set(e,t)}run(e,t,r,i,a){tt(e.programInfo.name);let n=this.backend.device,s=this.backend.getComputePassEncoder();this.backend.writeTimestamp(this.backend.pendingDispatchNumber*2);let o=[];for(let l of t)o.push({binding:o.length,resource:{buffer:l.buffer}});for(let l of r)o.push({binding:o.length,resource:{buffer:l.buffer}});a&&o.push({binding:o.length,resource:a});let u=n.createBindGroup({layout:e.computePipeline.getBindGroupLayout(0),entries:o,label:e.programInfo.name});if(this.backend.sessionStatus==="capturing"){let l={kernelId:this.backend.currentKernelId,computePipeline:e.computePipeline,bindGroup:u,dispatchGroup:i};this.backend.capturedCommandList.get(this.backend.currentSessionId).push(l)}s.setPipeline(e.computePipeline),s.setBindGroup(0,u),s.dispatchWorkgroups(...i),this.backend.writeTimestamp(this.backend.pendingDispatchNumber*2+1),this.backend.pendingDispatchNumber++,(this.backend.pendingDispatchNumber>=this.backend.maxDispatchNumber||this.backend.queryType==="at-passes")&&this.backend.endComputePass(),this.backend.pendingDispatchNumber>=this.backend.maxDispatchNumber&&this.backend.flush(),Xe(e.programInfo.name)}dispose(){}build(e,t){tt(e.name);let r=this.backend.device,i=[];[{feature:"shader-f16",extension:"f16"},{feature:"subgroups",extension:"subgroups"}].forEach(l=>{r.features.has(l.feature)&&i.push(`enable ${l.extension};`)});let a=Se(t,this.backend.device.limits),n=e.getShaderSource(a),s=`${i.join(`
`)}
${a.additionalImplementations}
${n}`,o=r.createShaderModule({code:s,label:e.name});Ae("verbose",()=>`[WebGPU] ${e.name} shader code: ${s}`);let u=r.createComputePipeline({compute:{module:o,entryPoint:"main"},layout:"auto",label:e.name});return Xe(e.name),{programInfo:e,computePipeline:u,uniformVariablesInfo:a.variablesInfo}}normalizeDispatchGroupSize(e){let t=typeof e=="number"?e:e.x,r=typeof e=="number"?1:e.y||1,i=typeof e=="number"?1:e.z||1,a=this.backend.device.limits.maxComputeWorkgroupsPerDimension;if(t<=a&&r<=a&&i<=a)return[t,r,i];let n=t*r*i,s=Math.ceil(Math.sqrt(n));if(s>a){if(s=Math.ceil(Math.cbrt(n)),s>a)throw new Error("Total dispatch size exceeds WebGPU maximum.");return[s,s,s]}else return[s,s,1]}}}),_p={};H(_p,{WebGpuBackend:()=>xp});var bp,$p,vp,xp,rh=I(()=>{Ye(),ue(),yt(),ir(),Ja(),eh(),th(),bp=(e,t)=>{if(t.length!==e.length)throw new Error(`inputDependencies length ${t.length} is not equal to inputTensors length ${e.length}.`);let r=[];for(let i=0;i<e.length;++i){let a=e[i].dataType;switch(t[i]){case"none":{r.push("");break}case"type":{r.push(`${a}`);break}case"rank":{let n=e[i].dims.length;r.push(`${a};${n}`);break}case"dims":{let n=e[i].dims.join(",");r.push(`${a};${n}`);break}default:throw new Error(`unsupported input dependency: ${t[i]}`)}}return r.join("|")},$p=(e,t,r)=>{let i=e.name;return e.shaderCache?.hint&&(i+="["+e.shaderCache.hint+"]"),i+=":"+r+`:${bp(t,e.shaderCache?.inputDependencies??new Array(t.length).fill("dims"))}`,i},vp=class{constructor(e){e&&(this.architecture=e.architecture,this.vendor=e.vendor)}isArchitecture(e){return this.architecture===e}isVendor(e){return this.vendor===e}},xp=class{constructor(){this.currentSessionId=null,this.currentKernelId=null,this.commandEncoder=null,this.computePassEncoder=null,this.maxDispatchNumber=16,this.pendingDispatchNumber=0,this.pendingKernels=[],this.pendingQueries=new Map,this.sessionStatus="default",this.capturedCommandList=new Map,this.capturedPendingKernels=new Map,this.sessionExternalDataMapping=new Map}get currentKernelCustomData(){if(this.currentKernelId===null)throw new Error("currentKernelCustomData(): currentKernelId is null. (should not happen)");let e=this.kernelCustomData.get(this.currentKernelId);return e||(e={},this.kernelCustomData.set(this.currentKernelId,e)),e}async initialize(e,t){this.env=e;let r=[],i={requiredLimits:{maxComputeWorkgroupStorageSize:t.limits.maxComputeWorkgroupStorageSize,maxComputeWorkgroupsPerDimension:t.limits.maxComputeWorkgroupsPerDimension,maxStorageBufferBindingSize:t.limits.maxStorageBufferBindingSize,maxBufferSize:t.limits.maxBufferSize,maxComputeInvocationsPerWorkgroup:t.limits.maxComputeInvocationsPerWorkgroup,maxComputeWorkgroupSizeX:t.limits.maxComputeWorkgroupSizeX,maxComputeWorkgroupSizeY:t.limits.maxComputeWorkgroupSizeY,maxComputeWorkgroupSizeZ:t.limits.maxComputeWorkgroupSizeZ},requiredFeatures:r},a=n=>t.features.has(n)&&r.push(n)&&!0;a("chromium-experimental-timestamp-query-inside-passes")||a("timestamp-query"),a("shader-f16"),a("subgroups"),this.device=await t.requestDevice(i),this.adapterInfo=new vp(t.info||await t.requestAdapterInfo()),this.gpuDataManager=va(this),this.programManager=new wp(this),this.kernels=new Map,this.kernelPersistentData=new Map,this.kernelCustomData=new Map,Jr(e.logLevel,!!e.debug),this.device.onuncapturederror=n=>{n.error instanceof GPUValidationError&&console.error(`An uncaught WebGPU validation error was raised: ${n.error.message}`)},Object.defineProperty(this.env.webgpu,"device",{value:this.device,writable:!1,enumerable:!0,configurable:!1}),Object.defineProperty(this.env.webgpu,"adapter",{value:t,writable:!1,enumerable:!0,configurable:!1}),this.setQueryType()}dispose(){typeof this.querySet<"u"&&this.querySet.destroy(),this.gpuDataManager.dispose()}getCommandEncoder(){return this.commandEncoder||(this.commandEncoder=this.device.createCommandEncoder()),this.commandEncoder}getComputePassEncoder(){if(!this.computePassEncoder){let e=this.getCommandEncoder(),t={};this.queryType==="at-passes"&&(t.timestampWrites={querySet:this.querySet,beginningOfPassWriteIndex:this.pendingDispatchNumber*2,endOfPassWriteIndex:this.pendingDispatchNumber*2+1}),this.computePassEncoder=e.beginComputePass(t)}return this.computePassEncoder}endComputePass(){this.computePassEncoder&&(this.computePassEncoder.end(),this.computePassEncoder=null)}flush(){if(!this.commandEncoder)return;tt(),this.endComputePass();let e;this.queryType!=="none"&&(this.commandEncoder.resolveQuerySet(this.querySet,0,this.pendingDispatchNumber*2,this.queryResolveBuffer,0),e=this.device.createBuffer({size:this.pendingDispatchNumber*2*8,usage:GPUBufferUsage.MAP_READ|GPUBufferUsage.COPY_DST}),this.pendingQueries.set(e,this.pendingKernels),this.pendingKernels=[],this.commandEncoder.copyBufferToBuffer(this.queryResolveBuffer,0,e,0,this.pendingDispatchNumber*2*8)),this.device.queue.submit([this.commandEncoder.finish()]),this.gpuDataManager.refreshPendingBuffers(),this.commandEncoder=null,this.pendingDispatchNumber=0,this.queryType!=="none"&&e.mapAsync(GPUMapMode.READ).then(()=>{let t=new BigUint64Array(e.getMappedRange()),r=this.pendingQueries.get(e);for(let i=0;i<t.length/2;i++){let a=r[i],n=a.kernelId,s=this.kernels.get(n),o=s.kernelType,u=s.kernelName,l=a.programName,d=a.inputTensorViews,p=a.outputTensorViews,h=t[i*2],f=t[i*2+1];typeof this.queryTimeBase>"u"&&(this.queryTimeBase=h);let m=Number(h-this.queryTimeBase),w=Number(f-this.queryTimeBase);if(!Number.isSafeInteger(m)||!Number.isSafeInteger(w))throw new RangeError("incorrect timestamp range");if(this.env.webgpu.profiling?.ondata)this.env.webgpu.profiling.ondata({version:1,inputsMetadata:d.map($=>({dims:$.dims,dataType:ft($.dataType)})),outputsMetadata:p.map($=>({dims:$.dims,dataType:ft($.dataType)})),kernelId:n,kernelType:o,kernelName:u,programName:l,startTime:m,endTime:w});else{let $="";d.forEach((y,S)=>{$+=`input[${S}]: [${y.dims}] | ${ft(y.dataType)}, `});let _="";p.forEach((y,S)=>{_+=`output[${S}]: [${y.dims}] | ${ft(y.dataType)}, `}),console.log(`[profiling] kernel "${n}|${o}|${u}|${l}" ${$}${_}start time: ${m} ns, execution time: ${w-m} ns`)}Ut("GPU",`${l}::${h}::${f}`)}e.unmap(),this.pendingQueries.delete(e)}),Xe()}run(e,t,r,i,a,n){tt(e.name);let s=[];for(let y=0;y<t.length;++y){let S=t[y].data;if(S===0)continue;let v=this.gpuDataManager.get(S);if(!v)throw new Error(`no GPU data for input: ${S}`);s.push(v)}let{outputs:o,dispatchGroup:u,programUniforms:l}=e.getRunData(t),d=r.length===0?o.map((y,S)=>S):r;if(d.length!==o.length)throw new Error(`Output size ${d.length} must be equal to ${o.length}.`);let p=[],h=[];for(let y=0;y<o.length;++y){if(!Number.isInteger(d[y])||d[y]<-3||d[y]>=n)throw new Error(`Invalid output index: ${d[y]}`);if(d[y]===-3)continue;let S=d[y]===-1,v=d[y]===-2,E=S||v?a(o[y].dataType,o[y].dims):i(d[y],o[y].dataType,o[y].dims);if(p.push(E),E.data===0)continue;let B=this.gpuDataManager.get(E.data);if(!B)throw new Error(`no GPU data for output: ${E.data}`);if(S&&this.temporaryData.push(B),v){let R=this.kernelPersistentData.get(this.currentKernelId);R||(R=[],this.kernelPersistentData.set(this.currentKernelId,R)),R.push(B)}h.push(B)}if(s.length!==t.length||h.length!==p.length){if(h.length===0)return Xe(e.name),p;throw new Error(`Program ${e.name} has zero-sized tensor(s) in inputs or outputs. This is not supported now.`)}let f;if(l){let y=0,S=[];l.forEach(R=>{let U=typeof R.data=="number"?[R.data]:R.data;if(U.length===0)return;let W=R.type===10?2:4,X,ke;R.type===10?(ke=U.length>4?16:U.length>2?8:U.length*W,X=U.length>4?16:W*U.length):(ke=U.length<=2?U.length*W:16,X=16),y=Math.ceil(y/ke)*ke,S.push(y);let ae=R.type===10?8:4;y+=U.length>4?Math.ceil(U.length/ae)*X:U.length*W});let v=16;y=Math.ceil(y/v)*v;let E=new ArrayBuffer(y);l.forEach((R,U)=>{let W=S[U],X=typeof R.data=="number"?[R.data]:R.data;if(R.type===6)new Int32Array(E,W,X.length).set(X);else if(R.type===12)new Uint32Array(E,W,X.length).set(X);else if(R.type===10)new Uint16Array(E,W,X.length).set(X);else if(R.type===1)new Float32Array(E,W,X.length).set(X);else throw new Error(`Unsupported uniform type: ${ft(R.type)}`)});let B=this.gpuDataManager.create(y,GPUBufferUsage.COPY_DST|GPUBufferUsage.UNIFORM);this.device.queue.writeBuffer(B.buffer,0,E,0,y),this.gpuDataManager.release(B.id),f={offset:0,size:y,buffer:B.buffer}}let m=this.programManager.normalizeDispatchGroupSize(u),w=m[1]===1&&m[2]===1,$=$p(e,t,w),_=this.programManager.getArtifact($);if(_||(_=this.programManager.build(e,m),this.programManager.setArtifact($,_),Ae("info",()=>`[artifact] key: ${$}, programName: ${e.name}`)),l&&_.uniformVariablesInfo){if(l.length!==_.uniformVariablesInfo.length)throw new Error(`Uniform variables count mismatch: expect ${_.uniformVariablesInfo.length}, got ${l.length} in program "${_.programInfo.name}".`);for(let y=0;y<l.length;y++){let S=l[y],v=S.type,E=typeof S.data=="number"?1:S.data.length,[B,R]=_.uniformVariablesInfo[y];if(v!==B||E!==R)throw new Error(`Uniform variable ${y} mismatch: expect type ${B} with size ${R}, got type ${v} with size ${E} in program "${_.programInfo.name}".`)}}if(Ae("info",()=>`[ProgramManager] run "${e.name}" (key=${$}) with ${m[0]}x${m[1]}x${m[2]}`),this.queryType!=="none"||this.sessionStatus==="capturing"){let y={kernelId:this.currentKernelId,programName:_.programInfo.name,inputTensorViews:t,outputTensorViews:p};this.pendingKernels.push(y),this.sessionStatus==="capturing"&&this.capturedPendingKernels.get(this.currentSessionId).push(y)}return this.programManager.run(_,s,h,m,f),Xe(e.name),p}upload(e,t){this.gpuDataManager.upload(e,t)}memcpy(e,t){this.gpuDataManager.memcpy(e,t)}async download(e,t){await this.gpuDataManager.download(e,t)}alloc(e){return this.gpuDataManager.create(e).id}free(e){return this.gpuDataManager.release(e)}createKernel(e,t,r,i){let a=yp.get(e);if(!a)throw new Error(`kernel not implemented: ${e}`);let n={kernelType:e,kernelName:i,kernelEntry:a[0],attributes:[a[1],r]};this.kernels.set(t,n)}releaseKernel(e){let t=this.kernelPersistentData.get(e);if(t){for(let r of t)this.gpuDataManager.release(r.id);this.kernelPersistentData.delete(e)}this.kernelCustomData.delete(e),this.kernels.delete(e)}computeKernel(e,t,r){let i=this.kernels.get(e);if(!i)throw new Error(`kernel not created: ${e}`);let a=i.kernelType,n=i.kernelName,s=i.kernelEntry,o=i.attributes;if(this.currentKernelId!==null)throw new Error(`kernel "[${a}] ${n}" is not allowed to be called recursively`);this.currentKernelId=e,o[0]&&(o[1]=o[0](o[1]),o[0]=void 0),Ae("info",()=>`[WebGPU] Start to run kernel "[${a}] ${n}"...`);let u=this.env.debug;this.temporaryData=[];try{return u&&this.device.pushErrorScope("validation"),s(t,o[1]),0}catch(l){return r.push(Promise.resolve(`[WebGPU] Kernel "[${a}] ${n}" failed. ${l}`)),1}finally{u&&r.push(this.device.popErrorScope().then(l=>l?`GPU validation error for kernel "[${a}] ${n}": ${l.message}`:null));for(let l of this.temporaryData)this.gpuDataManager.release(l.id);this.temporaryData=[],this.currentKernelId=null}}registerBuffer(e,t,r,i){let a=this.sessionExternalDataMapping.get(e);a||(a=new Map,this.sessionExternalDataMapping.set(e,a));let n=a.get(t),s=this.gpuDataManager.registerExternalBuffer(r,i,n);return a.set(t,[s,r]),s}unregisterBuffers(e){let t=this.sessionExternalDataMapping.get(e);t&&(t.forEach(r=>this.gpuDataManager.unregisterExternalBuffer(r[0])),this.sessionExternalDataMapping.delete(e))}getBuffer(e){let t=this.gpuDataManager.get(e);if(!t)throw new Error(`no GPU data for buffer: ${e}`);return t.buffer}createDownloader(e,t,r){return async()=>{let i=await Ki(this,e,t);return Vt(i.buffer,r)}}writeTimestamp(e){this.queryType==="inside-passes"&&this.computePassEncoder.writeTimestamp(this.querySet,e)}setQueryType(){this.queryType="none",(this.env.webgpu.profiling?.mode==="default"||(typeof this.env.trace>"u"?this.env.wasm.trace:this.env.trace))&&(this.device.features.has("chromium-experimental-timestamp-query-inside-passes")?this.queryType="inside-passes":this.device.features.has("timestamp-query")&&(this.queryType="at-passes"),this.queryType!=="none"&&typeof this.querySet>"u"&&(this.querySet=this.device.createQuerySet({type:"timestamp",count:this.maxDispatchNumber*2}),this.queryResolveBuffer=this.device.createBuffer({size:this.maxDispatchNumber*2*8,usage:GPUBufferUsage.COPY_SRC|GPUBufferUsage.QUERY_RESOLVE})))}captureBegin(){Ae("info","captureBegin"),this.capturedCommandList.get(this.currentSessionId)||this.capturedCommandList.set(this.currentSessionId,[]),this.capturedPendingKernels.get(this.currentSessionId)||this.capturedPendingKernels.set(this.currentSessionId,[]),this.flush(),this.sessionStatus="capturing"}captureEnd(){Ae("info","captureEnd"),this.flush(),this.sessionStatus="default"}replay(){Ae("info","replay"),this.sessionStatus="replaying";let e=this.capturedCommandList.get(this.currentSessionId),t=this.capturedPendingKernels.get(this.currentSessionId),r=e.length;this.pendingKernels=[];for(let i=0;i<r;i++){let a=this.getComputePassEncoder(),n=e[i];this.writeTimestamp(this.pendingDispatchNumber*2),a.setPipeline(n.computePipeline),a.setBindGroup(0,n.bindGroup),a.dispatchWorkgroups(...n.dispatchGroup),this.writeTimestamp(this.pendingDispatchNumber*2+1),this.pendingDispatchNumber++,this.queryType!=="none"&&this.pendingKernels.push(t[i]),(this.pendingDispatchNumber>=this.maxDispatchNumber||this.queryType==="at-passes")&&this.endComputePass(),this.pendingDispatchNumber>=this.maxDispatchNumber&&this.flush()}this.flush(),this.sessionStatus="default"}onCreateSession(){this.gpuDataManager.onCreateSession()}onReleaseSession(e){this.unregisterBuffers(e),this.capturedCommandList.has(e)&&this.capturedCommandList.delete(e),this.capturedPendingKernels.has(e)&&this.capturedPendingKernels.delete(e),this.gpuDataManager.onReleaseSession(e)}onRunStart(e){this.currentSessionId=e,this.setQueryType()}}}),Sp={};H(Sp,{init:()=>Ep});var Ma,Tp,Ep,ih=I(()=>{ue(),yt(),oe(),Hi(),Ma=class pc{constructor(t,r,i,a){this.module=t,this.dataType=r,this.data=i,this.dims=a}getFloat32Array(){if(this.dataType!==1)throw new Error("Invalid data type");let t=M.size(this.dims);return t===0?new Float32Array:new Float32Array(this.module.HEAP8.buffer,this.data,t)}getBigInt64Array(){if(this.dataType!==7)throw new Error("Invalid data type");let t=M.size(this.dims);return t===0?new BigInt64Array:new BigInt64Array(this.module.HEAP8.buffer,this.data,t)}getInt32Array(){if(this.dataType!==6)throw new Error("Invalid data type");let t=M.size(this.dims);return t===0?new Int32Array:new Int32Array(this.module.HEAP8.buffer,this.data,t)}getUint16Array(){if(this.dataType!==10&&this.dataType!==4)throw new Error("Invalid data type");let t=M.size(this.dims);return t===0?new Uint16Array:new Uint16Array(this.module.HEAP8.buffer,this.data,t)}reshape(t){if(M.size(t)!==M.size(this.dims))throw new Error("Invalid new shape");return new pc(this.module,this.dataType,this.data,t)}},Tp=class{constructor(e,t,r){this.module=e,this.backend=t,this.customDataOffset=0,this.customDataSize=0,this.adapterInfo=t.adapterInfo;let i=e.PTR_SIZE,a=r/e.PTR_SIZE,n=i===4?"i32":"i64";this.opKernelContext=Number(e.getValue(i*a++,n));let s=Number(e.getValue(i*a++,n));this.outputCount=Number(e.getValue(i*a++,n)),this.customDataOffset=Number(e.getValue(i*a++,"*")),this.customDataSize=Number(e.getValue(i*a++,n));let o=[];for(let u=0;u<s;u++){let l=Number(e.getValue(i*a++,n)),d=Number(e.getValue(i*a++,"*")),p=Number(e.getValue(i*a++,n)),h=[];for(let f=0;f<p;f++)h.push(Number(e.getValue(i*a++,n)));o.push(new Ma(e,l,d,h))}this.inputs=o}get kernelCustomData(){return this.backend.currentKernelCustomData}get customDataBuffer(){return this.module.HEAPU8.subarray(this.customDataOffset,this.customDataOffset+this.customDataSize)}compute(e,t){let r=t?.inputs?.map(s=>typeof s=="number"?this.inputs[s]:s)??this.inputs,i=t?.outputs??[],a=(s,o,u)=>new Ma(this.module,o,this.output(s,u),u),n=(s,o)=>{let u=mt(s,o);if(!u)throw new Error(`Unsupported data type: ${s}`);let l=u>0?this.backend.gpuDataManager.create(u).id:0;return new Ma(this.module,s,l,o)};return this.backend.run(e,r,i,a,n,this.outputCount)}output(e,t){let r=this.module.stackSave();try{let i=this.module.PTR_SIZE,a=i===4?"i32":"i64",n=this.module.stackAlloc((1+t.length)*i);this.module.setValue(n,t.length,a);for(let s=0;s<t.length;s++)this.module.setValue(n+i*(s+1),t[s],a);return this.module._JsepOutput(this.opKernelContext,e,n)}catch(i){throw new Error(`Failed to generate kernel's output[${e}] with dims [${t}]. If you are running with pre-allocated output, please make sure the output type/dims are correct. Error: ${i}`)}finally{this.module.stackRestore(r)}}},Ep=async(e,t,r,i)=>{let a=t.jsepInit;if(!a)throw new Error("Failed to initialize JSEP. The WebAssembly module is not built with JSEP support.");if(e==="webgpu"){let n=(rh(),we(_p)).WebGpuBackend,s=new n;await s.initialize(r,i),a("webgpu",[s,o=>s.alloc(Number(o)),o=>s.free(o),(o,u,l,d=!1)=>{if(d)Ae("verbose",()=>`[WebGPU] jsepCopyGpuToGpu: src=${Number(o)}, dst=${Number(u)}, size=${Number(l)}`),s.memcpy(Number(o),Number(u));else{Ae("verbose",()=>`[WebGPU] jsepCopyCpuToGpu: dataOffset=${Number(o)}, gpuDataId=${Number(u)}, size=${Number(l)}`);let p=t.HEAPU8.subarray(Number(o>>>0),Number(o>>>0)+Number(l));s.upload(Number(u),p)}},async(o,u,l)=>{Ae("verbose",()=>`[WebGPU] jsepCopyGpuToCpu: gpuDataId=${o}, dataOffset=${u}, size=${l}`),await s.download(Number(o),()=>t.HEAPU8.subarray(Number(u)>>>0,Number(u+l)>>>0))},(o,u,l)=>s.createKernel(o,Number(u),l,t.UTF8ToString(t._JsepGetNodeName(Number(u)))),o=>s.releaseKernel(o),(o,u,l,d)=>{Ae("verbose",()=>`[WebGPU] jsepRun: sessionHandle=${l}, kernel=${o}, contextDataOffset=${u}`);let p=new Tp(t,s,Number(u));return s.computeKernel(Number(o),p,d)},()=>s.captureBegin(),()=>s.captureEnd(),()=>s.replay()])}else{let n=new ji(r);a("webnn",[n,()=>n.reserveTensorId(),s=>n.releaseTensorId(s),async(s,o,u,l,d)=>n.ensureTensor(s,o,u,l,d),(s,o)=>{n.uploadTensor(s,o)},async(s,o)=>n.downloadTensor(s,o),(s,o)=>n.registerMLContext(s,o),!!r.trace])}}}),kp,Wn,Gn,ur,Ip,jn,Da,Hn,Kn,Zn,Qn,Xn,Yn,Cp=I(()=>{Ye(),Xa(),Ya(),ue(),ct(),Cr(),Li(),kp=(e,t)=>{ce()._OrtInit(e,t)!==0&&se("Can't initialize onnxruntime.")},Wn=async e=>{kp(e.wasm.numThreads,Ar(e.logLevel))},Gn=async(e,t)=>{ce().asyncInit?.();let r=e.webgpu.adapter;if(t==="webgpu"){if(typeof navigator>"u"||!navigator.gpu)throw new Error("WebGPU is not supported in current environment");if(r){if(typeof r.limits!="object"||typeof r.features!="object"||typeof r.requestDevice!="function")throw new Error("Invalid GPU adapter set in `env.webgpu.adapter`. It must be a GPUAdapter object.")}else{let i=e.webgpu.powerPreference;if(i!==void 0&&i!=="low-power"&&i!=="high-performance")throw new Error(`Invalid powerPreference setting: "${i}"`);let a=e.webgpu.forceFallbackAdapter;if(a!==void 0&&typeof a!="boolean")throw new Error(`Invalid forceFallbackAdapter setting: "${a}"`);if(r=await navigator.gpu.requestAdapter({powerPreference:i,forceFallbackAdapter:a}),!r)throw new Error('Failed to get GPU adapter. You may need to enable flag "--enable-unsafe-webgpu" if you are using Chrome.')}}if(t==="webnn"&&(typeof navigator>"u"||!navigator.ml))throw new Error("WebNN is not supported in current environment");{let i=(ih(),we(Sp)).init;t==="webgpu"&&await i("webgpu",ce(),e,r),t==="webnn"&&await i("webnn",ce(),e)}},ur=new Map,Ip=e=>{let t=ce(),r=t.stackSave();try{let i=t.PTR_SIZE,a=t.stackAlloc(2*i);t._OrtGetInputOutputCount(e,a,a+i)!==0&&se("Can't get session input/output count.");let n=i===4?"i32":"i64";return[Number(t.getValue(a,n)),Number(t.getValue(a+i,n))]}finally{t.stackRestore(r)}},jn=(e,t)=>{let r=ce(),i=r.stackSave(),a=0;try{let n=r.PTR_SIZE,s=r.stackAlloc(2*n);r._OrtGetInputOutputMetadata(e,t,s,s+n)!==0&&se("Can't get session input/output metadata.");let o=Number(r.getValue(s,"*"));a=Number(r.getValue(s+n,"*"));let u=r.HEAP32[a/4];if(u===0)return[o,0];let l=r.HEAPU32[a/4+1],d=[];for(let p=0;p<l;p++){let h=Number(r.getValue(a+8+p*n,"*"));d.push(h!==0?r.UTF8ToString(h):Number(r.getValue(a+8+(p+l)*n,"*")))}return[o,u,d]}finally{r.stackRestore(i),a!==0&&r._OrtFree(a)}},Da=e=>{let t=ce(),r=t._malloc(e.byteLength);if(r===0)throw new Error(`Can't create a session. failed to allocate a buffer of size ${e.byteLength}.`);return t.HEAPU8.set(e,r),[r,e.byteLength]},Hn=async(e,t)=>{let r,i,a=ce();Array.isArray(e)?[r,i]=e:e.buffer===a.HEAPU8.buffer?[r,i]=[e.byteOffset,e.byteLength]:[r,i]=Da(e);let n=0,s=0,o=0,u=[],l=[],d=[];try{if([s,u]=await Ni(t),t?.externalData&&a.mountExternalData){let v=[];for(let E of t.externalData){let B=typeof E=="string"?E:E.path;v.push(Br(typeof E=="string"?E:E.data).then(R=>{a.mountExternalData(B,R)}))}await Promise.all(v)}for(let v of t?.executionProviders??[])if((typeof v=="string"?v:v.name)==="webnn"){if(a.shouldTransferToMLTensor=!1,typeof v!="string"){let E=v,B=E?.context,R=E?.gpuDevice,U=E?.deviceType,W=E?.powerPreference;B?a.currentContext=B:R?a.currentContext=await a.webnnCreateMLContext(R):a.currentContext=await a.webnnCreateMLContext({deviceType:U,powerPreference:W})}else a.currentContext=await a.webnnCreateMLContext();break}n=await a._OrtCreateSession(r,i,s),a.webgpuOnCreateSession?.(n),n===0&&se("Can't create a session."),a.jsepOnCreateSession?.(),a.currentContext&&(a.webnnRegisterMLContext(n,a.currentContext),a.currentContext=void 0,a.shouldTransferToMLTensor=!0);let[p,h]=Ip(n),f=!!t?.enableGraphCapture,m=[],w=[],$=[],_=[],y=[];for(let v=0;v<p;v++){let[E,B,R]=jn(n,v);E===0&&se("Can't get an input name."),l.push(E);let U=a.UTF8ToString(E);m.push(U),$.push(B===0?{name:U,isTensor:!1}:{name:U,isTensor:!0,type:ft(B),shape:R})}for(let v=0;v<h;v++){let[E,B,R]=jn(n,v+p);E===0&&se("Can't get an output name."),d.push(E);let U=a.UTF8ToString(E);w.push(U),_.push(B===0?{name:U,isTensor:!1}:{name:U,isTensor:!0,type:ft(B),shape:R});{if(f&&t?.preferredOutputLocation===void 0){y.push("gpu-buffer");continue}let W=typeof t?.preferredOutputLocation=="string"?t.preferredOutputLocation:t?.preferredOutputLocation?.[U]??"cpu",X=a.webnnIsGraphOutput;if(W==="cpu"&&X&&X(n,U)){y.push("ml-tensor-cpu-output");continue}if(W!=="cpu"&&W!=="cpu-pinned"&&W!=="gpu-buffer"&&W!=="ml-tensor")throw new Error(`Not supported preferred output location: ${W}.`);if(f&&W!=="gpu-buffer")throw new Error(`Not supported preferred output location: ${W}. Only 'gpu-buffer' location is supported when enableGraphCapture is true.`);y.push(W)}}let S=null;return y.some(v=>v==="gpu-buffer"||v==="ml-tensor"||v==="ml-tensor-cpu-output")&&(o=a._OrtCreateBinding(n),o===0&&se("Can't create IO binding."),S={handle:o,outputPreferredLocations:y,outputPreferredLocationsEncoded:y.map(v=>v==="ml-tensor-cpu-output"?"ml-tensor":v).map(v=>Qr(v))}),ur.set(n,[n,l,d,S,f,!1]),[n,m,w,$,_]}catch(p){throw l.forEach(h=>a._OrtFree(h)),d.forEach(h=>a._OrtFree(h)),o!==0&&a._OrtReleaseBinding(o)!==0&&se("Can't release IO binding."),n!==0&&a._OrtReleaseSession(n)!==0&&se("Can't release session."),p}finally{a._free(r),s!==0&&a._OrtReleaseSessionOptions(s)!==0&&se("Can't release session options."),u.forEach(p=>a._free(p)),a.unmountExternalData?.()}},Kn=e=>{let t=ce(),r=ur.get(e);if(!r)throw new Error(`cannot release session. invalid session id: ${e}`);let[i,a,n,s,o]=r;s&&(o&&t._OrtClearBoundOutputs(s.handle)!==0&&se("Can't clear bound outputs."),t._OrtReleaseBinding(s.handle)!==0&&se("Can't release IO binding.")),t.jsepOnReleaseSession?.(e),t.webnnOnReleaseSession?.(e),t.webgpuOnReleaseSession?.(e),a.forEach(u=>t._OrtFree(u)),n.forEach(u=>t._OrtFree(u)),t._OrtReleaseSession(i)!==0&&se("Can't release session."),ur.delete(e)},Zn=async(e,t,r,i,a,n,s=!1)=>{if(!e){t.push(0);return}let o=ce(),u=o.PTR_SIZE,l=e[0],d=e[1],p=e[3],h=p,f,m;if(l==="string"&&(p==="gpu-buffer"||p==="ml-tensor"))throw new Error("String tensor is not supported on GPU.");if(s&&p!=="gpu-buffer")throw new Error(`External buffer must be provided for input/output index ${n} when enableGraphCapture is true.`);if(p==="gpu-buffer"){let _=e[2].gpuBuffer;m=mt(ht(l),d);{let y=o.jsepRegisterBuffer;if(!y)throw new Error('Tensor location "gpu-buffer" is not supported without using WebGPU.');f=y(i,n,_,m)}}else if(p==="ml-tensor"){let _=e[2].mlTensor;m=mt(ht(l),d);let y=o.webnnRegisterMLTensor;if(!y)throw new Error('Tensor location "ml-tensor" is not supported without using WebNN.');f=y(i,_,ht(l),d)}else{let _=e[2];if(Array.isArray(_)){m=u*_.length,f=o._malloc(m),r.push(f);for(let y=0;y<_.length;y++){if(typeof _[y]!="string")throw new TypeError(`tensor data at index ${y} is not a string`);o.setValue(f+y*u,He(_[y],r),"*")}}else{let y=o.webnnIsGraphInput,S=o.webnnIsGraphOutput;if(l!=="string"&&y&&S){let v=o.UTF8ToString(a);if(y(i,v)||S(i,v)){let E=ht(l);m=mt(E,d),h="ml-tensor";let B=o.webnnCreateTemporaryTensor,R=o.webnnUploadTensor;if(!B||!R)throw new Error('Tensor location "ml-tensor" is not supported without using WebNN.');let U=await B(i,E,d);R(U,new Uint8Array(_.buffer,_.byteOffset,_.byteLength)),f=U}else m=_.byteLength,f=o._malloc(m),r.push(f),o.HEAPU8.set(new Uint8Array(_.buffer,_.byteOffset,m),f)}else m=_.byteLength,f=o._malloc(m),r.push(f),o.HEAPU8.set(new Uint8Array(_.buffer,_.byteOffset,m),f)}}let w=o.stackSave(),$=o.stackAlloc(4*d.length);try{d.forEach((y,S)=>o.setValue($+S*u,y,u===4?"i32":"i64"));let _=o._OrtCreateTensor(ht(l),f,m,$,d.length,Qr(h));_===0&&se(`Can't create tensor for input/output. session=${i}, index=${n}.`),t.push(_)}finally{o.stackRestore(w)}},Qn=async(e,t,r,i,a,n)=>{let s=ce(),o=s.PTR_SIZE,u=ur.get(e);if(!u)throw new Error(`cannot run inference. invalid session id: ${e}`);let l=u[0],d=u[1],p=u[2],h=u[3],f=u[4],m=u[5],w=t.length,$=i.length,_=0,y=[],S=[],v=[],E=[],B=[],R=s.stackSave(),U=s.stackAlloc(w*o),W=s.stackAlloc(w*o),X=s.stackAlloc($*o),ke=s.stackAlloc($*o);try{[_,y]=Bi(n),st("wasm prepareInputOutputTensor");for(let j=0;j<w;j++)await Zn(r[j],S,E,e,d[t[j]],t[j],f);for(let j=0;j<$;j++)await Zn(a[j],v,E,e,p[i[j]],w+i[j],f);ot("wasm prepareInputOutputTensor");for(let j=0;j<w;j++)s.setValue(U+j*o,S[j],"*"),s.setValue(W+j*o,d[t[j]],"*");for(let j=0;j<$;j++)s.setValue(X+j*o,v[j],"*"),s.setValue(ke+j*o,p[i[j]],"*");if(h&&!m){let{handle:j,outputPreferredLocations:re,outputPreferredLocationsEncoded:Ie}=h;if(d.length!==w)throw new Error(`input count from feeds (${w}) is expected to be always equal to model's input count (${d.length}).`);st("wasm bindInputsOutputs");for(let be=0;be<w;be++){let fe=t[be];await s._OrtBindInput(j,d[fe],S[be])!==0&&se(`Can't bind input[${be}] for session=${e}.`)}for(let be=0;be<$;be++){let fe=i[be];a[be]?.[3]?(B.push(v[be]),s._OrtBindOutput(j,p[fe],v[be],0)!==0&&se(`Can't bind pre-allocated output[${be}] for session=${e}.`)):s._OrtBindOutput(j,p[fe],0,Ie[fe])!==0&&se(`Can't bind output[${be}] to ${re[be]} for session=${e}.`)}ot("wasm bindInputsOutputs"),ur.set(e,[l,d,p,h,f,!0])}s.jsepOnRunStart?.(l),s.webnnOnRunStart?.(l);let ae;h?ae=await s._OrtRunWithBinding(l,h.handle,$,X,_):ae=await s._OrtRun(l,W,U,w,ke,$,X,_),ae!==0&&se("failed to call OrtRun().");let de=[],Me=[];st("wasm ProcessOutputTensor");for(let j=0;j<$;j++){let re=Number(s.getValue(X+j*o,"*"));if(re===v[j]||B.includes(v[j])){de.push(a[j]),re!==v[j]&&s._OrtReleaseTensor(re)!==0&&se("Can't release tensor.");continue}let Ie=s.stackSave(),be=s.stackAlloc(4*o),fe=!1,De,L=0;try{s._OrtGetTensorData(re,be,be+o,be+2*o,be+3*o)!==0&&se(`Can't access output tensor data on index ${j}.`);let K=o===4?"i32":"i64",$e=Number(s.getValue(be,K));L=s.getValue(be+o,"*");let Pe=s.getValue(be+o*2,"*"),Dt=Number(s.getValue(be+o*3,K)),Gt=[];for(let nt=0;nt<Dt;nt++)Gt.push(Number(s.getValue(Pe+nt*o,K)));s._OrtFree(Pe)!==0&&se("Can't free memory for tensor dims.");let dr=Gt.reduce((nt,Qe)=>nt*Qe,1);De=ft($e);let la=h?.outputPreferredLocations[i[j]];if(De==="string"){if(la==="gpu-buffer"||la==="ml-tensor")throw new Error("String tensor is not supported on GPU.");let nt=[];for(let Qe=0;Qe<dr;Qe++){let Yt=s.getValue(L+Qe*o,"*"),uh=s.getValue(L+(Qe+1)*o,"*"),lh=Qe===dr-1?void 0:uh-Yt;nt.push(s.UTF8ToString(Yt,lh))}de.push([De,Gt,nt,"cpu"])}else if(la==="gpu-buffer"&&dr>0){let nt=s.jsepGetBuffer;if(!nt)throw new Error('preferredLocation "gpu-buffer" is not supported without using WebGPU.');let Qe=nt(L),Yt=mt($e,dr);if(Yt===void 0||!Or(De))throw new Error(`Unsupported data type: ${De}`);fe=!0,de.push([De,Gt,{gpuBuffer:Qe,download:s.jsepCreateDownloader(Qe,Yt,De),dispose:()=>{s._OrtReleaseTensor(re)!==0&&se("Can't release tensor.")}},"gpu-buffer"])}else if(la==="ml-tensor"&&dr>0){let nt=s.webnnEnsureTensor,Qe=s.webnnIsGraphInputOutputTypeSupported;if(!nt||!Qe)throw new Error('preferredLocation "ml-tensor" is not supported without using WebNN.');if(mt($e,dr)===void 0||!Rr(De))throw new Error(`Unsupported data type: ${De}`);if(!Qe(e,De,!1))throw new Error(`preferredLocation "ml-tensor" for ${De} output is not supported by current WebNN Context.`);let Yt=await nt(e,L,$e,Gt,!1);fe=!0,de.push([De,Gt,{mlTensor:Yt,download:s.webnnCreateMLTensorDownloader(L,De),dispose:()=>{s.webnnReleaseTensorId(L),s._OrtReleaseTensor(re)}},"ml-tensor"])}else if(la==="ml-tensor-cpu-output"&&dr>0){let nt=s.webnnCreateMLTensorDownloader(L,De)(),Qe=de.length;fe=!0,Me.push((async()=>{let Yt=[Qe,await nt];return s.webnnReleaseTensorId(L),s._OrtReleaseTensor(re),Yt})()),de.push([De,Gt,[],"cpu"])}else{let nt=zr(De),Qe=new nt(dr);new Uint8Array(Qe.buffer,Qe.byteOffset,Qe.byteLength).set(s.HEAPU8.subarray(L,L+Qe.byteLength)),de.push([De,Gt,Qe,"cpu"])}}finally{s.stackRestore(Ie),De==="string"&&L&&s._free(L),fe||s._OrtReleaseTensor(re)}}h&&!f&&(s._OrtClearBoundOutputs(h.handle)!==0&&se("Can't clear bound outputs."),ur.set(e,[l,d,p,h,f,!1]));for(let[j,re]of await Promise.all(Me))de[j][2]=re;return ot("wasm ProcessOutputTensor"),de}finally{s.webnnOnRunEnd?.(l),s.stackRestore(R),S.forEach(ae=>s._OrtReleaseTensor(ae)),v.forEach(ae=>s._OrtReleaseTensor(ae)),E.forEach(ae=>s._free(ae)),_!==0&&s._OrtReleaseRunOptions(_),y.forEach(ae=>s._free(ae))}},Xn=e=>{let t=ce(),r=ur.get(e);if(!r)throw new Error("invalid session id");let i=r[0],a=t._OrtEndProfiling(i);a===0&&se("Can't get an profile file name."),t._OrtFree(a)},Yn=e=>{let t=[];for(let r of e){let i=r[2];!Array.isArray(i)&&"buffer"in i&&t.push(i.buffer)}return t}}),lr,vt,fi,oa,ua,Pa,Jn,Ua,jr,Hr,zp,Ap,Op,Rp,Bp,Mp,Dp,Pp,Up=I(()=>{Ye(),Cp(),ct(),Tr(),lr=()=>!!ie.wasm.proxy&&typeof document<"u",fi=!1,oa=!1,ua=!1,Ua=new Map,jr=(e,t)=>{let r=Ua.get(e);r?r.push(t):Ua.set(e,[t])},Hr=()=>{if(fi||!oa||ua||!vt)throw new Error("worker not ready")},zp=e=>{switch(e.data.type){case"init-wasm":fi=!1,e.data.err?(ua=!0,Jn[1](e.data.err)):(oa=!0,Jn[0]()),Pa&&(URL.revokeObjectURL(Pa),Pa=void 0);break;case"init-ep":case"copy-from":case"create":case"release":case"run":case"end-profiling":{let t=Ua.get(e.data.type);e.data.err?t.shift()[1](e.data.err):t.shift()[0](e.data.out);break}}},Ap=async()=>{if(!oa){if(fi)throw new Error("multiple calls to 'initWasm()' detected.");if(ua)throw new Error("previous call to 'initWasm()' failed.");if(fi=!0,lr())return new Promise((e,t)=>{vt?.terminate(),Ci().then(([r,i])=>{try{vt=i,vt.onerror=n=>t(n),vt.onmessage=zp,Jn=[e,t];let a={type:"init-wasm",in:ie};if(!a.in.wasm.wasmPaths&&r){let n=$r();n&&(a.in.wasm.wasmPaths=n)}vt.postMessage(a),Pa=r}catch(a){t(a)}},t)});try{await Ir(ie.wasm),await Wn(ie),oa=!0}catch(e){throw ua=!0,e}finally{fi=!1}}},Op=async e=>{if(lr())return Hr(),new Promise((t,r)=>{jr("init-ep",[t,r]);let i={type:"init-ep",in:{epName:e,env:ie}};vt.postMessage(i)});await Gn(ie,e)},Rp=async e=>lr()?(Hr(),new Promise((t,r)=>{jr("copy-from",[t,r]);let i={type:"copy-from",in:{buffer:e}};vt.postMessage(i,[e.buffer])})):Da(e),Bp=async(e,t)=>{if(lr()){if(t?.preferredOutputLocation)throw new Error('session option "preferredOutputLocation" is not supported for proxy.');return Hr(),new Promise((r,i)=>{jr("create",[r,i]);let a={type:"create",in:{model:e,options:{...t}}},n=[];e instanceof Uint8Array&&n.push(e.buffer),vt.postMessage(a,n)})}else return Hn(e,t)},Mp=async e=>{if(lr())return Hr(),new Promise((t,r)=>{jr("release",[t,r]);let i={type:"release",in:e};vt.postMessage(i)});Kn(e)},Dp=async(e,t,r,i,a,n)=>{if(lr()){if(r.some(s=>s[3]!=="cpu"))throw new Error("input tensor on GPU is not supported for proxy.");if(a.some(s=>s))throw new Error("pre-allocated output tensor is not supported for proxy.");return Hr(),new Promise((s,o)=>{jr("run",[s,o]);let u=r,l={type:"run",in:{sessionId:e,inputIndices:t,inputs:u,outputIndices:i,options:n}};vt.postMessage(l,Yn(u))})}else return Qn(e,t,r,i,a,n)},Pp=async e=>{if(lr())return Hr(),new Promise((t,r)=>{jr("end-profiling",[t,r]);let i={type:"end-profiling",in:e};vt.postMessage(i)});Xn(e)}}),es,Np,Lp,ah=I(()=>{Ye(),Up(),ue(),wr(),Li(),es=(e,t)=>{switch(e.location){case"cpu":return[e.type,e.dims,e.data,"cpu"];case"gpu-buffer":return[e.type,e.dims,{gpuBuffer:e.gpuBuffer},"gpu-buffer"];case"ml-tensor":return[e.type,e.dims,{mlTensor:e.mlTensor},"ml-tensor"];default:throw new Error(`invalid data location: ${e.location} for ${t()}`)}},Np=e=>{switch(e[3]){case"cpu":return new je(e[0],e[2],e[1]);case"gpu-buffer":{let t=e[0];if(!Or(t))throw new Error(`not supported data type: ${t} for deserializing GPU tensor`);let{gpuBuffer:r,download:i,dispose:a}=e[2];return je.fromGpuBuffer(r,{dataType:t,dims:e[1],download:i,dispose:a})}case"ml-tensor":{let t=e[0];if(!Rr(t))throw new Error(`not supported data type: ${t} for deserializing MLTensor tensor`);let{mlTensor:r,download:i,dispose:a}=e[2];return je.fromMLTensor(r,{dataType:t,dims:e[1],download:i,dispose:a})}default:throw new Error(`invalid data location: ${e[3]}`)}},Lp=class{async fetchModelAndCopyToWasmMemory(e){return Rp(await Br(e))}async loadModel(e,t){tt();let r;typeof e=="string"?r=await this.fetchModelAndCopyToWasmMemory(e):r=e,[this.sessionId,this.inputNames,this.outputNames,this.inputMetadata,this.outputMetadata]=await Bp(r,t),Xe()}async dispose(){return Mp(this.sessionId)}async run(e,t,r){tt();let i=[],a=[];Object.entries(e).forEach(p=>{let h=p[0],f=p[1],m=this.inputNames.indexOf(h);if(m===-1)throw new Error(`invalid input '${h}'`);i.push(f),a.push(m)});let n=[],s=[];Object.entries(t).forEach(p=>{let h=p[0],f=p[1],m=this.outputNames.indexOf(h);if(m===-1)throw new Error(`invalid output '${h}'`);n.push(f),s.push(m)});let o=i.map((p,h)=>es(p,()=>`input "${this.inputNames[a[h]]}"`)),u=n.map((p,h)=>p?es(p,()=>`output "${this.outputNames[s[h]]}"`):null),l=await Dp(this.sessionId,a,o,s,u,r),d={};for(let p=0;p<l.length;p++)d[this.outputNames[s[p]]]=n[p]??Np(l[p]);return Xe(),d}startProfiling(){}endProfiling(){Pp(this.sessionId)}}}),Vp={};H(Vp,{OnnxruntimeWebAssemblyBackend:()=>rs,initializeFlags:()=>ts,wasmBackend:()=>qp});var ts,rs,qp,nh=I(()=>{Ye(),Up(),ah(),ts=()=>{(typeof ie.wasm.initTimeout!="number"||ie.wasm.initTimeout<0)&&(ie.wasm.initTimeout=0);let e=ie.wasm.simd;if(typeof e!="boolean"&&e!==void 0&&e!=="fixed"&&e!=="relaxed"&&(console.warn(`Property "env.wasm.simd" is set to unknown value "${e}". Reset it to \`false\` and ignore SIMD feature checking.`),ie.wasm.simd=!1),typeof ie.wasm.proxy!="boolean"&&(ie.wasm.proxy=!1),typeof ie.wasm.trace!="boolean"&&(ie.wasm.trace=!1),typeof ie.wasm.numThreads!="number"||!Number.isInteger(ie.wasm.numThreads)||ie.wasm.numThreads<=0)if(typeof self<"u"&&!self.crossOriginIsolated)ie.wasm.numThreads=1;else{let t=typeof navigator>"u"?G("node:os").cpus().length:navigator.hardwareConcurrency;ie.wasm.numThreads=Math.min(4,Math.ceil((t||1)/2))}},rs=class{async init(e){ts(),await Ap(),await Op(e)}async createInferenceSessionHandler(e,t){let r=new Lp;return await r.loadModel(e,t),r}},qp=new rs}),Fp={};H(Fp,{InferenceSession:()=>yr,TRACE:()=>Ut,TRACE_EVENT_BEGIN:()=>st,TRACE_EVENT_END:()=>ot,TRACE_FUNC_BEGIN:()=>tt,TRACE_FUNC_END:()=>Xe,Tensor:()=>je,default:()=>oh,env:()=>ie,registerBackend:()=>Q}),Ye(),Ye(),Ye();var sh="1.24.3",oh=$i;{let e=(nh(),we(Vp)).wasmBackend;Q("webgpu",e,5),Q("webnn",e,5),Q("cpu",e,10),Q("wasm",e,10)}return Object.defineProperty(ie.versions,"web",{value:sh,enumerable:!0}),we(Fp)})();F.exports=Oe})(ss)),ss.exports}var ga={},rc;function cc(){if(rc)return ga;rc=1,Object.defineProperty(ga,"__esModule",{value:!0}),ga.Resampler=void 0;const F=_a();class ge{constructor(ye){this.options=ye,this.process=ve=>{const me=[];for(const J of ve)for(this.inputBuffer.push(J);this.hasEnoughDataForFrame();){const G=this.generateOutputFrame();me.push(G)}return me},ye.nativeSampleRate<16e3&&F.log.error("nativeSampleRate is too low. Should have 16000 = targetSampleRate <= nativeSampleRate"),this.inputBuffer=[]}async*stream(ye){for(const ve of ye)for(this.inputBuffer.push(ve);this.hasEnoughDataForFrame();)yield this.generateOutputFrame()}hasEnoughDataForFrame(){return this.inputBuffer.length*this.options.targetSampleRate/this.options.nativeSampleRate>=this.options.targetFrameSize}generateOutputFrame(){const ye=new Float32Array(this.options.targetFrameSize);let ve=0,me=0;for(;ve<this.options.targetFrameSize;){let J=0,G=0;for(;me<Math.min(this.inputBuffer.length,(ve+1)*this.options.nativeSampleRate/this.options.targetSampleRate);){const I=this.inputBuffer[me];I!==void 0&&(J+=I,G++),me++}ye[ve]=J/G,ve++}return this.inputBuffer=this.inputBuffer.slice(me),ye}}return ga.Resampler=ge,ga}var ic;function xh(){return ic||(ic=1,(function(F){var ge=er&&er.__createBinding||(Object.create?(function(he,ne,Q,Y){Y===void 0&&(Y=Q);var Ce=Object.getOwnPropertyDescriptor(ne,Q);(!Ce||("get"in Ce?!ne.__esModule:Ce.writable||Ce.configurable))&&(Ce={enumerable:!0,get:function(){return ne[Q]}}),Object.defineProperty(he,Y,Ce)}):(function(he,ne,Q,Y){Y===void 0&&(Y=Q),he[Y]=ne[Q]})),Oe=er&&er.__setModuleDefault||(Object.create?(function(he,ne){Object.defineProperty(he,"default",{enumerable:!0,value:ne})}):function(he,ne){he.default=ne}),ye=er&&er.__importStar||function(he){if(he&&he.__esModule)return he;var ne={};if(he!=null)for(var Q in he)Q!=="default"&&Object.prototype.hasOwnProperty.call(he,Q)&&ge(ne,he,Q);return Oe(ne,he),ne};Object.defineProperty(F,"__esModule",{value:!0}),F.NonRealTimeVAD=F.defaultNonRealTimeVADOptions=void 0;const ve=ye(vh()),me=lc(),J=ls(),G=Va(),I=ba(),H=us(),le=cc();F.defaultNonRealTimeVADOptions={...G.defaultFrameProcessorOptions,modelURL:me.baseAssetPath+"silero_vad_legacy.onnx",modelFetcher:J.defaultModelFetcher};class we{static async new(ne={}){const Q={...F.defaultNonRealTimeVADOptions,...ne};(0,G.validateOptions)(Q),Q.ortConfig!==void 0&&Q.ortConfig(ve);const Y=()=>Q.modelFetcher(Q.modelURL),Ce=await H.SileroLegacy.new(ve,Y),Ne=new G.FrameProcessor(Ce.process,Ce.reset_state,{positiveSpeechThreshold:Q.positiveSpeechThreshold,negativeSpeechThreshold:Q.negativeSpeechThreshold,redemptionMs:Q.redemptionMs,preSpeechPadMs:Q.preSpeechPadMs,minSpeechMs:Q.minSpeechMs,submitUserSpeechOnPause:Q.submitUserSpeechOnPause},1536/16);return Ne.resume(),new this(Y,ve,Q,Ne)}constructor(ne,Q,Y,Ce){this.modelFetcher=ne,this.ort=Q,this.options=Y,this.frameProcessor=Ce,this.frameSamples=1536}async*run(ne,Q){const Y={nativeSampleRate:Q,targetSampleRate:16e3,targetFrameSize:this.frameSamples},Ce=new le.Resampler(Y);let Ne=0,ze=0,Te=0;for await(const Re of Ce.stream(ne)){const pe=[];await this.frameProcessor.process(Re,Fe=>{pe.push(Fe)});for(const Fe of pe)switch(Fe.msg){case I.Message.SpeechStart:Ne=Te*this.frameSamples/16;break;case I.Message.SpeechEnd:ze=(Te+1)*this.frameSamples/16,yield{audio:Fe.audio,start:Ne,end:ze};break}Te++}const _e=[];this.frameProcessor.endSegment(Re=>{_e.push(Re)});for(const Re of _e)Re.msg===I.Message.SpeechEnd&&(yield{audio:Re.audio,start:Ne,end:Te*this.frameSamples/16})}}F.NonRealTimeVAD=we})(er)),er}var Pt={},ac;function Sh(){if(ac)return Pt;ac=1,Object.defineProperty(Pt,"__esModule",{value:!0}),Pt.audioFileToArray=Pt.encodeWAV=Pt.arrayBufferToBase64=Pt.minFramesForTargetMS=void 0;function F(G,I,H=16e3){return Math.ceil(G*H/1e3/I)}Pt.minFramesForTargetMS=F;function ge(G){const I=new Uint8Array(G),H=I.byteLength,le=new Array(H);for(let we=0;we<H;we++){const he=I[we];if(he===void 0)break;le[we]=String.fromCharCode(he)}return btoa(le.join(""))}Pt.arrayBufferToBase64=ge;function Oe(G,I=3,H=16e3,le=1,we=32){const he=we/8,ne=le*he,Q=new ArrayBuffer(44+G.length*he),Y=new DataView(Q);return me(Y,0,"RIFF"),Y.setUint32(4,36+G.length*he,!0),me(Y,8,"WAVE"),me(Y,12,"fmt "),Y.setUint32(16,16,!0),Y.setUint16(20,I,!0),Y.setUint16(22,le,!0),Y.setUint32(24,H,!0),Y.setUint32(28,H*ne,!0),Y.setUint16(32,ne,!0),Y.setUint16(34,we,!0),me(Y,36,"data"),Y.setUint32(40,G.length*he,!0),I===1?ve(Y,44,G):ye(Y,44,G),Q}Pt.encodeWAV=Oe;function ye(G,I,H){for(let le=0;le<H.length;le++,I+=4)G.setFloat32(I,H[le],!0)}function ve(G,I,H){for(let le=0;le<H.length;le++,I+=2){const we=Math.max(-1,Math.min(1,H[le]));G.setInt16(I,we<0?we*32768:we*32767,!0)}}function me(G,I,H){for(let le=0;le<H.length;le++)G.setUint8(I+le,H.charCodeAt(le))}async function J(G){const I=new OfflineAudioContext(1,1,44100),H=new FileReader;let le=null;if(await new Promise(ne=>{H.addEventListener("loadend",()=>{const Q=H.result;I.decodeAudioData(Q,Y=>{le=Y,I.startRendering().then(()=>{console.log("Rendering completed successfully"),ne()}).catch(Ce=>{console.error("Rendering failed: ",Ce)})},Y=>{console.log("Error with decoding audio data: ",Y)})}),H.readAsArrayBuffer(G)}),le===null)throw Error("some shit");const we=le,he=new Float32Array(we.length);for(let ne=0;ne<we.length;ne++)for(let Q=0;Q<we.numberOfChannels;Q++){const Y=we.getChannelData(Q)[ne],Ce=he[ne];if(Y===void 0||Ce===void 0)throw new Error("sample or out[i] is undefined");he[ne]=Ce+Y}return{audio:he,sampleRate:we.sampleRate}}return Pt.audioFileToArray=J,Pt}var tr={},nc;function Th(){return nc||(nc=1,(function(F){var ge=tr&&tr.__createBinding||(Object.create?(function(ze,Te,_e,Re){Re===void 0&&(Re=_e);var pe=Object.getOwnPropertyDescriptor(Te,_e);(!pe||("get"in pe?!Te.__esModule:pe.writable||pe.configurable))&&(pe={enumerable:!0,get:function(){return Te[_e]}}),Object.defineProperty(ze,Re,pe)}):(function(ze,Te,_e,Re){Re===void 0&&(Re=_e),ze[Re]=Te[_e]})),Oe=tr&&tr.__setModuleDefault||(Object.create?(function(ze,Te){Object.defineProperty(ze,"default",{enumerable:!0,value:Te})}):function(ze,Te){ze.default=Te}),ye=tr&&tr.__importStar||function(ze){if(ze&&ze.__esModule)return ze;var Te={};if(ze!=null)for(var _e in ze)_e!=="default"&&Object.prototype.hasOwnProperty.call(ze,_e)&&ge(Te,ze,_e);return Oe(Te,ze),Te};Object.defineProperty(F,"__esModule",{value:!0}),F.MicVAD=F.getDefaultRealTimeVADOptions=F.ort=F.DEFAULT_MODEL=void 0;const ve=ye(uc()),me=ls(),J=Va(),G=_a(),I=ba(),H=us(),le=cc();F.DEFAULT_MODEL="legacy",F.ort=ve;const we="vad.worklet.bundle.min.js",he={legacy:"silero_vad_legacy.onnx",v5:"silero_vad_v5.onnx",v6:"silero_vad_v6.onnx"},ne=ze=>({...J.defaultFrameProcessorOptions,onFrameProcessed:()=>{},onVADMisfire:()=>{G.log.debug("VAD misfire")},onSpeechStart:()=>{G.log.debug("Detected speech start")},onSpeechEnd:()=>{G.log.debug("Detected speech end")},onSpeechRealStart:()=>{G.log.debug("Detected real speech start")},baseAssetPath:"./",onnxWASMBasePath:"./",model:ze,workletOptions:{},getStream:async()=>await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:!0,autoGainControl:!0,noiseSuppression:!0}}),pauseStream:async Te=>{Te.getTracks().forEach(_e=>{_e.stop()})},resumeStream:async()=>await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:!0,autoGainControl:!0,noiseSuppression:!0}}),ortConfig:Te=>{Te.env.logLevel="error"},startOnLoad:!0,processorType:"auto"});F.getDefaultRealTimeVADOptions=ne;const Q=ze=>"audioWorklet"in ze&&typeof AudioWorkletNode=="function"?"AudioWorklet":"ScriptProcessor";async function Y(ze,Te,_e,Re,pe){await _e.audioWorklet.addModule(ze),Te.processorOptions={...Te.processorOptions??{},frameSamples:Re};const Fe=new AudioWorkletNode(_e,"vad-helper-worklet",Te);return Fe.port.onmessage=async ie=>{const et=ie.data;if(!(typeof et=="object"&&et&&"message"in et)){console.error("Invalid message event",et);return}switch(et.message){case I.Message.AudioFrame:{if(!("data"in et&&et.data instanceof ArrayBuffer)){console.log("Audio frame message has no data");return}const lt=new Float32Array(et.data);await pe(lt);break}}},Fe}async function Ce(ze,Te,_e){const Re=new le.Resampler({nativeSampleRate:ze.sampleRate,targetSampleRate:16e3,targetFrameSize:Te});G.log.debug("using script processor");const Fe=ze.createScriptProcessor(4096,1,1);let ie=!1;return Fe.onaudioprocess=async et=>{if(!ie){ie=!0;try{const lt=et.inputBuffer.getChannelData(0);et.outputBuffer.getChannelData(0).fill(0);const _t=Re.process(lt);for(const gt of _t)await _e(gt)}catch(lt){console.error("Error processing audio:",lt)}finally{ie=!1}}},Fe.connect(ze.destination),Fe}class Ne{constructor(Te,_e,Re,pe,Fe=!1,ie=null,et=null,lt=null,St=null,_t=null,gt=null,pr="uninitialized",cr=!1){this.options=Te,this.frameProcessor=_e,this.model=Re,this.frameSamples=pe,this.listening=Fe,this.errored=ie,this._stream=et,this._audioContext=lt,this._vadNode=St,this._mediaStreamAudioSourceNode=_t,this._audioProcessorAdapterType=gt,this.initializationState=pr,this.ownsAudioContext=cr,this.getAudioInstances=()=>{if(this._stream===null||this._audioContext===null||this._vadNode==null||this._mediaStreamAudioSourceNode==null)throw new Error("MicVAD has null stream, audio context, or processor adapter");return{stream:this._stream,audioContext:this._audioContext,vadNode:this._vadNode,mediaStreamAudioSourceNode:this._mediaStreamAudioSourceNode}},this.setErrored=Ue=>{this.initializationState="errored",this.errored=Ue},this.start=async()=>{switch(this.initializationState){case"uninitialized":{G.log.debug("initializing micVAD"),this.initializationState="initializing",this.frameProcessor.resume();try{this._stream=await this.options.getStream()}catch(Ue){throw Ue instanceof Error?this.setErrored(Ue.message):this.setErrored(String(Ue)),Ue}if(this.options.audioContext?(console.log("using custom audio context"),this._audioContext=this.options.audioContext):(console.log("using default audio context"),this._audioContext=new AudioContext,this.ownsAudioContext=!0),!this._audioContext)throw this.setErrored("Audio context is null"),Error("Audio context is null");switch(this._audioProcessorAdapterType=this.options.processorType=="auto"?Q(this._audioContext):this.options.processorType,this._audioProcessorAdapterType){case"AudioWorklet":this._vadNode=await Y(this.options.baseAssetPath+we,this.options.workletOptions,this._audioContext,this.frameSamples,this.processFrame);break;case"ScriptProcessor":this._vadNode=await Ce(this._audioContext,this.frameSamples,this.processFrame);break;default:throw new Error(`Unsupported audio processor adapter type: ${this._audioProcessorAdapterType}`)}this._mediaStreamAudioSourceNode=new MediaStreamAudioSourceNode(this._audioContext,{mediaStream:this._stream}),this._mediaStreamAudioSourceNode.connect(this._vadNode),G.log.debug("started micVAD"),this.listening=!0,this.initializationState="initialized";break}case"initializing":{G.log.warn("start called while initializing");break}case"initialized":{if(this.listening)return;this.listening=!0,this.frameProcessor.resume();const{stream:Ue,audioContext:jt,vadNode:hr}=this.getAudioInstances();this._stream=await this.options.resumeStream(Ue);const Zr=new MediaStreamAudioSourceNode(jt,{mediaStream:this._stream});this._mediaStreamAudioSourceNode=Zr,Zr.connect(hr);break}case"destroyed":{G.log.warn("start called after destroyed");break}case"errored":{G.log.error("start called after errored");break}default:{G.log.warn("weird initialization state");break}}},this.pause=async()=>{if(!this.listening)return;this.listening=!1;const{stream:Ue,mediaStreamAudioSourceNode:jt}=this.getAudioInstances();await this.options.pauseStream(Ue),jt.disconnect(),this.frameProcessor.pause(this.handleFrameProcessorEvent)},this.destroy=async()=>{G.log.debug("destroy called"),this.initializationState="destroyed";const{vadNode:Ue}=this.getAudioInstances();Ue instanceof AudioWorkletNode&&Ue.port.postMessage(I.Message.SpeechStop),this.listening&&await this.pause(),await this.model.release(),this.ownsAudioContext&&await this._audioContext?.close()},this.setOptions=Ue=>{this.frameProcessor.setOptions(Ue)},this.processFrame=async Ue=>{await this.frameProcessor.process(Ue,this.handleFrameProcessorEvent)},this.handleFrameProcessorEvent=Ue=>{switch(Ue.msg){case I.Message.FrameProcessed:this.options.onFrameProcessed(Ue.probs,Ue.frame);break;case I.Message.SpeechStart:this.options.onSpeechStart();break;case I.Message.SpeechRealStart:this.options.onSpeechRealStart();break;case I.Message.VADMisfire:this.options.onVADMisfire();break;case I.Message.SpeechEnd:this.options.onSpeechEnd(Ue.audio);break}}}static async new(Te={}){const _e={...(0,F.getDefaultRealTimeVADOptions)(Te.model??F.DEFAULT_MODEL),...Te};(0,J.validateOptions)(_e),F.ort.env.wasm.wasmPaths=_e.onnxWASMBasePath,_e.ortConfig!==void 0&&_e.ortConfig(F.ort);const Re=_e.baseAssetPath+he[_e.model],pe=_e.model==="legacy"?H.SileroLegacy.new:H.Silero.new;let Fe;try{Fe=await pe(F.ort,()=>(0,me.defaultModelFetcher)(Re))}catch(_t){throw console.error(`Encountered an error while loading model file ${Re}`),_t}const ie=_e.model==="legacy"?1536:512,et=ie/16,lt=new J.FrameProcessor(Fe.process,Fe.reset_state,{positiveSpeechThreshold:_e.positiveSpeechThreshold,negativeSpeechThreshold:_e.negativeSpeechThreshold,redemptionMs:_e.redemptionMs,preSpeechPadMs:_e.preSpeechPadMs,minSpeechMs:_e.minSpeechMs,submitUserSpeechOnPause:_e.submitUserSpeechOnPause},et),St=new Ne(_e,lt,Fe,ie);if(_e.startOnLoad)try{await St.start()}catch(_t){throw console.error("Error starting micVad",_t),_t}return St}}F.MicVAD=Ne})(tr)),tr}var sc;function Eh(){return sc||(sc=1,(function(F){Object.defineProperty(F,"__esModule",{value:!0}),F.getDefaultRealTimeVADOptions=F.MicVAD=F.DEFAULT_MODEL=F.utils=F.NonRealTimeVAD=F.Message=F.FrameProcessor=F.defaultModelFetcher=F.baseAssetPath=void 0;var ge=lc();Object.defineProperty(F,"baseAssetPath",{enumerable:!0,get:function(){return ge.baseAssetPath}});var Oe=ls();Object.defineProperty(F,"defaultModelFetcher",{enumerable:!0,get:function(){return Oe.defaultModelFetcher}});var ye=Va();Object.defineProperty(F,"FrameProcessor",{enumerable:!0,get:function(){return ye.FrameProcessor}});var ve=ba();Object.defineProperty(F,"Message",{enumerable:!0,get:function(){return ve.Message}});var me=xh();Object.defineProperty(F,"NonRealTimeVAD",{enumerable:!0,get:function(){return me.NonRealTimeVAD}});const J=Sh();F.utils={audioFileToArray:J.audioFileToArray,minFramesForTargetMS:J.minFramesForTargetMS,arrayBufferToBase64:J.arrayBufferToBase64,encodeWAV:J.encodeWAV};var G=Th();Object.defineProperty(F,"DEFAULT_MODEL",{enumerable:!0,get:function(){return G.DEFAULT_MODEL}}),Object.defineProperty(F,"MicVAD",{enumerable:!0,get:function(){return G.MicVAD}}),Object.defineProperty(F,"getDefaultRealTimeVADOptions",{enumerable:!0,get:function(){return G.getDefaultRealTimeVADOptions}})})(ns)),ns}var kh=Eh();const os=`/assets/voice-${Gp["@ricky0123/vad-web"]}-${Gp["onnxruntime-web"]}/`,Ih=ph({message:hh(ya.Message.AudioFrame),data:ch(ArrayBuffer)}),Ch={load:()=>(La.env.wasm.wasmPaths=os,La.env.wasm.numThreads=1,$h.Silero.new(gh,async()=>{const F=await fetch(os+"silero_vad_v5.onnx");if(!F.ok)throw new Error("could not load the speech detection model");return F.arrayBuffer()})),worklet:async F=>(await F.audioWorklet.addModule(os+"vad.worklet.bundle.min.js"),new AudioWorkletNode(F,"vad-helper-worklet",{processorOptions:{frameSamples:512}}))};async function Oh(F,ge,Oe=Ch){const ye=F.audioContext;if(!ye)throw new Error("speech detection needs an AudioContext");const ve={...kh.getDefaultRealTimeVADOptions("v5"),...F},me=await Oe.load();let J=null,G=null,I=!1,H=!1,le=[],we=null;const he=Y=>{H||(Y.msg===ya.Message.SpeechStart&&ve.onSpeechStart(),Y.msg===ya.Message.SpeechEnd&&ve.onSpeechEnd(Y.audio),Y.msg===ya.Message.VADMisfire&&ve.onVADMisfire())},ne=new yh.FrameProcessor(me.process,me.reset_state,ve,32),Q=async()=>{H||(H=!0,I=!1,le=[],G?.disconnect(),J&&(J.port.onmessage=null,J.onprocessorerror=null,J.port.postMessage(ya.Message.SpeechStop),J.disconnect()),await we,await me.release())};try{J=await Oe.worklet(ye),G=ye.createMediaStreamSource(await ve.getStream()),G.connect(J);const Y=async()=>{try{for(;I&&!H&&le.length;){const Ce=le.shift();Ce&&await ne.process(Ce,he)}}catch(Ce){I=!1,le=[],ge(Ce)}finally{we=null}};return J.port.onmessage=Ce=>{if(!I||H)return;const Ne=Ih.safeParse(Ce.data);if(!(!Ne.success||Ne.data.data.byteLength!==512*4)){if(le.length>=64){I=!1,le=[],ge(new Error("speech detection cannot keep up on this device"));return}le.push(new Float32Array(Ne.data.data)),we??=Y()}},J.onprocessorerror=()=>{ge(new Error("speech detection audio worklet failed"))},{start:()=>H?Promise.reject(new Error("speech detector was released")):(I=!0,ne.resume(),Promise.resolve()),pause:async()=>{I=!1,le=[],await we,H||ne.pause(he)},destroy:Q}}catch(Y){throw await Q(),Y}}export{Oh as createSileroVad};
