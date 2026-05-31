/* ============================================================================
   Auto Trading — home.js
   Living solar core (Three.js, noise-displaced emissive icosahedron + particle
   galaxy + UnrealBloom) and GSAP scroll choreography. Progressive enhancement:
   data + content live in index.html and never depend on this module.
   ========================================================================== */
'use strict';

const PREFERS_REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const IS_TOUCH = window.matchMedia('(hover: none)').matches || navigator.maxTouchPoints > 1;
const IS_SMALL = window.matchMedia('(max-width: 820px)').matches;

/* Theme-aware palette for the WebGL scene (warm RiseWealth solar ramp). */
function scenePalette() {
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return light
    ? {
        page: '#FFF7F0',
        low: '#E9B488', mid: '#E55A1F', high: '#FFB877', rim: '#F26B1F',
        pA: '#C9461A', pB: '#E9913F',
        glow: 0.50, particleBlend: 'normal', particleAlpha: 0.55,
      }
    : {
        page: '#0E0805',
        low: '#280C03', mid: '#E0571C', high: '#FFC79A', rim: '#FF8A3D',
        pA: '#FF9A4D', pB: '#7A2C0E',
        glow: 0.92, particleBlend: 'add', particleAlpha: 0.9,
      };
}

/* Premium, theme-aware green/red for the candlestick chart. Up = emerald,
   down = crimson (realistic), price line stays brand gold so it reads as an
   overlay. Brighter/more saturated on dark, slightly deeper on light. */
function candlePalette() {
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return light
    ? {
        up: { low: '#0E7A3A', high: '#79E6A4', rim: '#16A34A' },
        down: { low: '#9C1325', high: '#FF7C8A', rim: '#DC2626' },
        line: { low: '#E55A1F', high: '#FFC79A', rim: '#FF8A3D' },
      }
    : {
        up: { low: '#0C5E2F', high: '#8AF7B9', rim: '#22C55E' },
        down: { low: '#7E1020', high: '#FF8B97', rim: '#EF4444' },
        line: { low: '#FF8A3D', high: '#FFE7CC', rim: '#FFB877' },
      };
}

/* ---------------------------------------------------------------------------
   GSAP choreography — reveals + hero load. Content stays visible if GSAP fails.
   ------------------------------------------------------------------------- */
function initMotion() {
  const gsap = window.gsap;
  if (!gsap || PREFERS_REDUCED) {
    document.documentElement.classList.remove('has-motion');
    return;
  }
  const ST = window.ScrollTrigger;
  if (ST) gsap.registerPlugin(ST);

  const fromVars = (el) => {
    const dir = el.getAttribute('data-reveal');
    return {
      opacity: 0,
      y: dir === 'up' ? 36 : 0,
      x: dir === 'left' ? 36 : 0,
      scale: dir === 'scale' ? 0.96 : 1,
    };
  };

  // Hero — orchestrated staggered load
  const heroEls = gsap.utils.toArray('#hero [data-reveal]');
  if (heroEls.length) {
    const tl = gsap.timeline({ delay: 0.12, defaults: { ease: 'expo.out', duration: 1.15 } });
    heroEls.forEach((el, i) => {
      tl.fromTo(el, fromVars(el), { opacity: 1, x: 0, y: 0, scale: 1 }, i === 0 ? 0 : '-=0.92');
    });
  }

  // Everything else reveals once on scroll (compositor-friendly: opacity +
  // transform only, fired a single time, then ScrollTrigger lets go).
  gsap.utils.toArray('[data-reveal]').forEach((el) => {
    if (el.closest('#hero')) return;
    gsap.fromTo(el, fromVars(el), {
      opacity: 1, x: 0, y: 0, scale: 1, duration: 0.9, ease: 'expo.out',
      clearProps: 'willChange',
      scrollTrigger: ST ? { trigger: el, start: 'top 88%', once: true } : undefined,
    });
  });
}

/* ---------------------------------------------------------------------------
   WebGL — the living solar core
   ------------------------------------------------------------------------- */
function webglSupported() {
  try {
    const c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')));
  } catch (_) { return false; }
}

const SIMPLEX = `
vec4 permute(vec4 x){return mod(((x*34.0)+1.0)*x,289.0);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0); const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.0-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+1.0*C.xxx; vec3 x2=x0-i2+2.0*C.xxx; vec3 x3=x0-1.0+3.0*C.xxx;
  i=mod(i,289.0);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=1.0/7.0; vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z);
  vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0; vec4 s1=floor(b1)*2.0+1.0; vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
  vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0); m=m*m;
  return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}`;

const CORE_VERT = `
${SIMPLEX}
uniform float uTime; uniform float uDisp; uniform float uIntensity;
varying float vDisp; varying vec3 vViewNormal; varying vec3 vViewDir;
float fbm(vec3 p){ float a=0.5,f=1.0,s=0.0; for(int i=0;i<3;i++){ s+=a*snoise(p*f); f*=2.0; a*=0.5; } return s; }
float displace(vec3 p){
  float n = fbm(p*1.25 + vec3(0.0, uTime*0.16, 0.0));
  n += 0.42 * snoise(p*0.7 - uTime*0.10);
  return n;
}
void main(){
  vec3 pos = position;
  float amp = uDisp * (0.82 + 0.55*uIntensity);
  float d = displace(pos);
  vec3 displaced = pos + normal * d * amp;
  // recompute normal via tangent-basis neighbour sampling
  vec3 tang = normalize(cross(normal, vec3(0.0,1.0,0.0) + 0.001));
  vec3 bitang = normalize(cross(normal, tang));
  float e = 0.16;
  vec3 da = (pos + tang*e) + normal * displace(pos + tang*e) * amp;
  vec3 db = (pos + bitang*e) + normal * displace(pos + bitang*e) * amp;
  vec3 nrm = normalize(cross(da - displaced, db - displaced));
  if(dot(nrm, normal) < 0.0) nrm = -nrm;
  vDisp = d;
  vec4 mv = modelViewMatrix * vec4(displaced, 1.0);
  vViewNormal = normalize(normalMatrix * nrm);
  vViewDir = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;

const CORE_FRAG = `
precision highp float;
uniform vec3 uLow; uniform vec3 uMid; uniform vec3 uHigh; uniform vec3 uRim;
varying float vDisp; varying vec3 vViewNormal; varying vec3 vViewDir;
void main(){
  float h = smoothstep(-0.65, 0.95, vDisp);
  vec3 base = mix(uLow, uMid, smoothstep(0.0, 0.62, h));
  base = mix(base, uHigh, smoothstep(0.58, 1.0, h));
  float fres = pow(1.0 - max(dot(normalize(vViewNormal), normalize(vViewDir)), 0.0), 2.5);
  vec3 col = base + uRim * fres * 1.25;
  col += uHigh * pow(h, 3.0) * 0.55;     // hot ridges glow for bloom
  gl_FragColor = vec4(col, 1.0);
}`;

const PART_VERT = `
uniform float uTime; uniform float uPixel; uniform float uSize; uniform float uIntensity;
attribute float aSize; attribute float aPhase; attribute float aRadius;
varying float vPhase; varying float vR;
void main(){
  vec3 p = position;
  float ang = uTime * 0.04 + aPhase * 0.4;
  mat2 r = mat2(cos(ang), -sin(ang), sin(ang), cos(ang));
  p.xz = r * p.xz;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = aSize * uSize * uPixel * (1.0 / -mv.z) * 36.0 * (0.9 + 0.3*uIntensity);
  gl_Position = projectionMatrix * mv;
  vPhase = aPhase; vR = aRadius;
}`;

const PART_FRAG = `
precision highp float;
uniform vec3 uColA; uniform vec3 uColB; uniform float uTime; uniform float uAlpha;
varying float vPhase; varying float vR;
void main(){
  vec2 uv = gl_PointCoord - 0.5;
  float d = length(uv);
  if(d > 0.5) discard;
  float a = smoothstep(0.5, 0.0, d);
  float tw = 0.55 + 0.45 * sin(uTime * 1.4 + vPhase * 6.2831);
  vec3 col = mix(uColA, uColB, smoothstep(2.2, 4.3, vR));
  gl_FragColor = vec4(col, a * tw * uAlpha);
}`;

/* Shared fresnel material for the station meshes (crystal / rings / knot). */
const MESH_VERT = `
varying vec3 vN; varying vec3 vView; varying vec3 vPos;
void main(){
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vN = normalize(normalMatrix * normal);
  vView = normalize(-mv.xyz);
  vPos = position;
  gl_Position = projectionMatrix * mv;
}`;
const MESH_FRAG = `
precision highp float;
uniform vec3 uLow; uniform vec3 uHigh; uniform vec3 uRim; uniform float uTime; uniform float uFlow;
varying vec3 vN; varying vec3 vView; varying vec3 vPos;
void main(){
  vec3 N = normalize(vN);
  float fres = pow(1.0 - max(dot(N, normalize(vView)), 0.0), 2.2);
  float flow = 0.5 + 0.5 * sin(vPos.y * 3.2 + vPos.x * 1.5 - uTime * 1.8);
  vec3 col = mix(uLow, uHigh, flow * uFlow + (1.0 - uFlow) * 0.35);
  col += uRim * fres * 1.45;
  gl_FragColor = vec4(col, 1.0);
}`;
/* Additive round points for the data globe. */
const GLOBE_VERT = `
uniform float uPix; uniform float uSize; attribute float aS;
void main(){
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = aS * uSize * uPix * (1.0 / -mv.z) * 34.0;
  gl_Position = projectionMatrix * mv;
}`;
const GLOBE_FRAG = `
precision highp float;
uniform vec3 uCol; uniform float uAlpha;
void main(){
  vec2 u = gl_PointCoord - 0.5; float d = length(u);
  if (d > 0.5) discard;
  gl_FragColor = vec4(uCol, smoothstep(0.5, 0.0, d) * uAlpha);
}`;

async function initScene(canvas, animate) {
  const THREE = await import('three');

  let pal = scenePalette();
  const dpr = Math.min(window.devicePixelRatio || 1, IS_SMALL ? 1 : 1.5);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !IS_SMALL, alpha: false, powerPreference: 'high-performance' });
  renderer.setPixelRatio(dpr);
  renderer.setClearColor(new THREE.Color(pal.page), 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0, 5.3);

  // Core
  const detail = IS_SMALL ? 8 : 12;
  const coreGeo = new THREE.IcosahedronGeometry(1.25, detail);
  const coreUni = {
    uTime: { value: 0 }, uDisp: { value: 0.34 }, uIntensity: { value: 0 },
    uLow: { value: new THREE.Color(pal.low) }, uMid: { value: new THREE.Color(pal.mid) },
    uHigh: { value: new THREE.Color(pal.high) }, uRim: { value: new THREE.Color(pal.rim) },
  };
  const coreMat = new THREE.ShaderMaterial({ vertexShader: CORE_VERT, fragmentShader: CORE_FRAG, uniforms: coreUni });
  const core = new THREE.Mesh(coreGeo, coreMat);
  scene.add(core);

  // Faint inner shell wireframe for depth
  const shellGeo = new THREE.IcosahedronGeometry(1.32, 2);
  const shellMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(pal.rim), wireframe: true, transparent: true, opacity: 0.06 });
  const shell = new THREE.Mesh(shellGeo, shellMat);
  scene.add(shell);

  // Particle galaxy
  const COUNT = IS_SMALL ? 1100 : 2200;
  const pos = new Float32Array(COUNT * 3);
  const aSize = new Float32Array(COUNT);
  const aPhase = new Float32Array(COUNT);
  const aRadius = new Float32Array(COUNT);
  for (let i = 0; i < COUNT; i++) {
    const r = 2.2 + Math.pow(Math.random(), 1.5) * 2.2;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    pos[i * 3 + 1] = r * Math.cos(phi) * 0.55;            // flatten into a disc
    pos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    aSize[i] = 0.5 + Math.random() * 1.7;
    aPhase[i] = Math.random();
    aRadius[i] = r;
  }
  const partGeo = new THREE.BufferGeometry();
  partGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  partGeo.setAttribute('aSize', new THREE.BufferAttribute(aSize, 1));
  partGeo.setAttribute('aPhase', new THREE.BufferAttribute(aPhase, 1));
  partGeo.setAttribute('aRadius', new THREE.BufferAttribute(aRadius, 1));
  const partUni = {
    uTime: { value: 0 }, uPixel: { value: dpr }, uSize: { value: 1 }, uIntensity: { value: 0 },
    uColA: { value: new THREE.Color(pal.pA) }, uColB: { value: new THREE.Color(pal.pB) }, uAlpha: { value: pal.particleAlpha },
  };
  const partMat = new THREE.ShaderMaterial({
    vertexShader: PART_VERT, fragmentShader: PART_FRAG, uniforms: partUni,
    transparent: true, depthWrite: false,
    blending: pal.particleBlend === 'add' ? THREE.AdditiveBlending : THREE.NormalBlending,
  });
  const particles = new THREE.Points(partGeo, partMat);
  particles.rotation.x = 0.5;
  scene.add(particles);

  // Cheap glow halo (replaces full-screen post-processing bloom): one additive
  // sprite with a radial gradient. Near-free, and keeps the molten look.
  const glowTex = (function () {
    const s = 128, c = document.createElement('canvas'); c.width = c.height = s;
    const x = c.getContext('2d');
    const g = x.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    g.addColorStop(0, 'rgba(255,180,110,0.95)');
    g.addColorStop(0.28, 'rgba(255,120,45,0.5)');
    g.addColorStop(1, 'rgba(255,90,30,0)');
    x.fillStyle = g; x.fillRect(0, 0, s, s);
    return new THREE.CanvasTexture(c);
  })();
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: glowTex, blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false,
    transparent: true, opacity: pal.glow,
  }));
  glow.scale.setScalar(5.4);

  // Core group, hosted inside a "world" group that tilts gently with the pointer.
  const group = new THREE.Group();
  group.add(glow); group.add(core); group.add(shell);
  const world = new THREE.Group();
  world.add(group);
  scene.add(world);

  // ---- Station objects: one shared renderer; only the in-view object draws ----
  const objMats = [], globeMats = [], wireMats = [], candleSet = [];
  function fresnelMat(flow) {
    const m = new THREE.ShaderMaterial({
      vertexShader: MESH_VERT, fragmentShader: MESH_FRAG,
      uniforms: {
        uTime: { value: 0 }, uFlow: { value: flow },
        uLow: { value: new THREE.Color(pal.mid) },
        uHigh: { value: new THREE.Color(pal.high) },
        uRim: { value: new THREE.Color(pal.rim) },
      },
    });
    objMats.push(m); return m;
  }
  function wireMesh(geo) {
    const m = new THREE.MeshBasicMaterial({ color: new THREE.Color(pal.rim), wireframe: true, transparent: true, opacity: 0.12 });
    wireMats.push(m); return new THREE.Mesh(geo, m);
  }
  function buildCrystal() {                       // A — faceted molten crystal
    const g = new THREE.IcosahedronGeometry(1.05, 1); g.computeVertexNormals();   // flat-faceted
    const mesh = new THREE.Mesh(g, fresnelMat(0.4));
    const wire = wireMesh(new THREE.IcosahedronGeometry(1.22, 1));
    const grp = new THREE.Group(); grp.add(mesh); grp.add(wire);
    grp.userData.update = (t) => { mesh.rotation.set(t * 0.12, t * 0.24, 0); wire.rotation.set(-t * 0.06, -t * 0.1, 0); mesh.material.uniforms.uTime.value = t; };
    return grp;
  }
  function buildRings() {                          // B — gyroscope rings
    const grp = new THREE.Group();
    const rs = [[0, 0, 0], [Math.PI / 2, 0, 0], [0, 0, Math.PI / 2]].map((r) => {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(1.0, 0.03, 10, IS_SMALL ? 80 : 140), fresnelMat(0.6));
      ring.rotation.set(r[0], r[1], r[2]); grp.add(ring); return ring;
    });
    const ball = new THREE.Mesh(new THREE.IcosahedronGeometry(0.34, 2), fresnelMat(0.85)); grp.add(ball);
    grp.userData.update = (t) => {
      rs[0].rotation.x = t * 0.5; rs[0].rotation.z = t * 0.2;
      rs[1].rotation.y = t * 0.62; rs[2].rotation.z = t * 0.44; rs[2].rotation.x = t * 0.2; ball.rotation.y = t * 0.5;
      grp.children.forEach((c) => { if (c.material && c.material.uniforms) c.material.uniforms.uTime.value = t; });
    };
    return grp;
  }
  function buildGlobe() {                          // C — data globe (points + wire)
    const N = IS_SMALL ? 700 : 1300;
    const pos = new Float32Array(N * 3), sz = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(Math.max(0, 1 - y * y)), th = i * 2.399963;
      pos[i * 3] = Math.cos(th) * r; pos[i * 3 + 1] = y; pos[i * 3 + 2] = Math.sin(th) * r;
      sz[i] = 0.5 + Math.random() * 1.3;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('aS', new THREE.BufferAttribute(sz, 1));
    const m = new THREE.ShaderMaterial({
      vertexShader: GLOBE_VERT, fragmentShader: GLOBE_FRAG, transparent: true, depthWrite: false,
      blending: pal.particleBlend === 'add' ? THREE.AdditiveBlending : THREE.NormalBlending,
      uniforms: { uPix: { value: dpr }, uSize: { value: 1 }, uCol: { value: new THREE.Color(pal.particleBlend === 'add' ? pal.high : pal.mid) }, uAlpha: { value: pal.particleAlpha } },
    });
    globeMats.push(m);
    const pts = new THREE.Points(geo, m); pts.scale.setScalar(1.15);
    const wire = wireMesh(new THREE.IcosahedronGeometry(1.05, 2));
    const grp = new THREE.Group(); grp.add(pts); grp.add(wire);
    grp.userData.update = (t) => { pts.rotation.y = t * 0.16; wire.rotation.set(0.3, t * 0.16, 0); };
    return grp;
  }
  function buildCandles() {                        // D — 3D candlestick chart (trading)
    const grp = new THREE.Group();
    const cp = candlePalette();
    const mkMat = (c, flow, role) => {
      const m = new THREE.ShaderMaterial({
        vertexShader: MESH_VERT, fragmentShader: MESH_FRAG,
        uniforms: { uTime: { value: 0 }, uFlow: { value: flow },
          uLow: { value: new THREE.Color(c.low) }, uHigh: { value: new THREE.Color(c.high) }, uRim: { value: new THREE.Color(c.rim) } },
      });
      candleSet.push({ mat: m, role }); return m;
    };
    const upMat = mkMat(cp.up, 0.45, 'up');       // emerald = up bar
    const downMat = mkMat(cp.down, 0.45, 'down'); // crimson = down bar
    const lineMat = mkMat(cp.line, 0.9, 'line');  // gold glowing price line + marker
    const mats = [upMat, downMat, lineMat];
    const N = IS_SMALL ? 11 : 15, W = 2.6, gap = W / N;
    let price = -0.55; const closes = []; let minY = 1e9, maxY = -1e9;
    for (let i = 0; i < N; i++) {
      const open = price;
      price += 0.05 + (Math.random() - 0.5) * 0.5 - price * 0.06;   // uptrend + volatility, gently bounded
      const close = price;
      const hi = Math.max(open, close) + Math.random() * 0.16 + 0.05;
      const lo = Math.min(open, close) - Math.random() * 0.16 - 0.05;
      const mat = close >= open ? upMat : downMat;
      const bt = Math.max(open, close), bb = Math.min(open, close);
      const x = (i - (N - 1) / 2) * gap;
      const body = new THREE.Mesh(new THREE.BoxGeometry(gap * 0.56, Math.max(0.1, bt - bb), gap * 0.56), mat);
      body.position.set(x, (bt + bb) / 2, 0); grp.add(body);
      const wick = new THREE.Mesh(new THREE.BoxGeometry(gap * 0.12, hi - lo, gap * 0.12), mat);
      wick.position.set(x, (hi + lo) / 2, 0); grp.add(wick);
      closes.push(new THREE.Vector3(x, close, 0));
      minY = Math.min(minY, lo); maxY = Math.max(maxY, hi);
    }
    const cy = (minY + maxY) / 2;
    const curve = new THREE.CatmullRomCurve3(closes);
    const line = new THREE.Mesh(new THREE.TubeGeometry(curve, 100, 0.026, 7, false), lineMat);
    grp.add(line);
    const marker = new THREE.Mesh(new THREE.SphereGeometry(0.07, 16, 16), lineMat);
    grp.add(marker);
    grp.children.forEach((c) => { c.position.y -= cy; });          // vertically centre the chart
    grp.userData.update = (t) => {
      grp.rotation.y = Math.sin(t * 0.25) * 0.42;                  // keep it mostly face-on, gently swaying
      grp.rotation.x = -0.08 + Math.sin(t * 0.18) * 0.05;
      mats.forEach((m) => (m.uniforms.uTime.value = t));
      const u = (t * 0.11) % 1;                                    // live marker travels the price line
      const p = curve.getPointAt(u); marker.position.set(p.x, p.y - cy, p.z);
    };
    return grp;
  }
  const crystal = buildCrystal(), rings = buildRings(), globe = buildGlobe(), candles = buildCandles();
  [crystal, rings, globe, candles].forEach((o) => { o.visible = false; world.add(o); });

  const byId = (id) => document.getElementById(id);
  const stations = [
    { root: group, core: true, els: ['hero', 'closing'].map(byId).filter(Boolean) },
    { root: crystal, side: 1, els: [byId('sec-risk')].filter(Boolean) },
    { root: rings, side: -1, els: [byId('sec-auto')].filter(Boolean) },
    { root: globe, side: 1, els: [byId('sec-record')].filter(Boolean) },
    { root: candles, side: -1, els: [byId('sec-eng')].filter(Boolean) },
  ];
  stations.forEach((s) => { s.p = 0; });
  let coreXTarget = 0, coreScaleTarget = 1, baseY = 0.18, objX = 1.55, objScale = 1.05;
  function layout() {
    const w = window.innerWidth;
    if (w > 1080) { coreXTarget = 1.55; coreScaleTarget = 1.12; baseY = -0.15; objX = 1.55; objScale = 1.05; }
    else if (w > 820) { coreXTarget = 0.95; coreScaleTarget = 0.96; baseY = 0.1; objX = 1.0; objScale = 0.9; }
    else { coreXTarget = 0.1; coreScaleTarget = 0.66; baseY = 1.4; objX = 0.0; objScale = 0.66; }
  }
  layout();
  group.position.set(coreXTarget, baseY, 0);
  group.scale.setScalar(coreScaleTarget);

  const wrap = canvas.parentElement;
  let maxScroll = 1;
  function resize() {
    // Use the wrap's layout size (in CSS px) so the buffer stays crisp under the
    // site-wide html{zoom:.9}; window.innerWidth would under-size it.
    const w = wrap.clientWidth || window.innerWidth;
    const h = wrap.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    maxScroll = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
    layout();
  }
  resize();

  // Pointer parallax (desktop) / gentle auto-orbit (touch)
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  if (!IS_TOUCH && animate) {
    window.addEventListener('pointermove', (e) => {
      pointer.tx = (e.clientX / window.innerWidth - 0.5) * 2;
      pointer.ty = (e.clientY / window.innerHeight - 0.5) * 2;
    }, { passive: true });
  }

  // Scroll-driven intensity + recentre toward the closing
  let scrollProg = 0;
  function onScroll() {
    scrollProg = Math.min(window.scrollY / maxScroll, 1);
  }
  if (animate) window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // Theme reactivity
  function applyTheme() {
    pal = scenePalette();
    renderer.setClearColor(new THREE.Color(pal.page), 1);
    coreUni.uLow.value.set(pal.low); coreUni.uMid.value.set(pal.mid);
    coreUni.uHigh.value.set(pal.high); coreUni.uRim.value.set(pal.rim);
    shellMat.color.set(pal.rim);
    partUni.uColA.value.set(pal.pA); partUni.uColB.value.set(pal.pB);
    partUni.uAlpha.value = pal.particleAlpha;
    partMat.blending = pal.particleBlend === 'add' ? THREE.AdditiveBlending : THREE.NormalBlending;
    partMat.needsUpdate = true;
    glow.material.opacity = pal.glow;
    objMats.forEach((m) => { m.uniforms.uLow.value.set(pal.mid); m.uniforms.uHigh.value.set(pal.high); m.uniforms.uRim.value.set(pal.rim); });
    wireMats.forEach((m) => m.color.set(pal.rim));
    globeMats.forEach((m) => {
      m.uniforms.uCol.value.set(pal.particleBlend === 'add' ? pal.high : pal.mid);
      m.uniforms.uAlpha.value = pal.particleAlpha;
      m.blending = pal.particleBlend === 'add' ? THREE.AdditiveBlending : THREE.NormalBlending; m.needsUpdate = true;
    });
    const cp = candlePalette();
    candleSet.forEach(({ mat, role }) => {
      const c = cp[role];
      mat.uniforms.uLow.value.set(c.low); mat.uniforms.uHigh.value.set(c.high); mat.uniforms.uRim.value.set(c.rim);
    });
    if (!animate) renderer.render(scene, camera);
  }
  document.addEventListener('starta:themechange', applyTheme);

  const clock = new THREE.Clock();
  let running = true, frame = 0;

  function renderFrame() {
    const t = clock.getElapsedTime();
    coreUni.uTime.value = t; partUni.uTime.value = t;
    const intensity = 0.35 + scrollProg * 0.9;
    coreUni.uIntensity.value += (intensity - coreUni.uIntensity.value) * 0.05;
    partUni.uIntensity.value = coreUni.uIntensity.value;

    pointer.x += (pointer.tx - pointer.x) * 0.04;
    pointer.y += (pointer.ty - pointer.y) * 0.04;

    core.rotation.y = t * 0.12 + pointer.x * 0.5;
    core.rotation.x = pointer.y * 0.35;
    shell.rotation.copy(core.rotation);
    particles.rotation.y = t * 0.025;

    // gentle pointer parallax on the whole station world
    world.rotation.y += (pointer.x * 0.12 - world.rotation.y) * 0.05;
    world.rotation.x += (-pointer.y * 0.08 - world.rotation.x) * 0.05;

    // Station crossfade: each object scales in only while its section is centred;
    // everything else is hidden (no draw call). One object active at a time.
    const rtl = document.documentElement.dir === 'rtl' ? -1 : 1;
    const vh = window.innerHeight, reach = vh * 0.62;
    for (let i = 0; i < stations.length; i++) {
      const s = stations[i];
      let target = 0, act = 0;
      for (let c = 0; c < s.els.length; c++) {
        const r = s.els[c].getBoundingClientRect();
        const center = r.top + r.height * 0.5;        // px from viewport top (zoom-consistent)
        const pp = Math.max(0, 1 - Math.abs(center - vh * 0.5) / reach);
        if (pp > target) { target = pp; act = c; }
      }
      s.p += (target - s.p) * 0.12;
      const e = s.p < 0.003 ? 0 : s.p * s.p * (3 - 2 * s.p);
      if (s.core) {
        const tx = (act === 1 && s.els.length > 1) ? 0 : coreXTarget * rtl;   // flip to the open side in RTL; centre at the closing
        group.position.x += (tx - group.position.x) * 0.06;
        group.position.y += (baseY - group.position.y) * 0.06;
        group.visible = e > 0.01;
        group.scale.setScalar(Math.max(0.0001, coreScaleTarget * e));
      } else {
        s.root.visible = e > 0.02;
        if (s.root.visible) {
          s.root.position.set(s.side * rtl * objX, 0, 0);
          s.root.scale.setScalar(Math.max(0.0001, objScale * e));
          s.root.userData.update(t);
        }
      }
    }

    renderer.render(scene, camera);
  }

  function loop() {
    if (!running) return;
    frame = requestAnimationFrame(loop);
    renderFrame();   // frames are cheap (one cull-gated object active at a time)
  }

  window.addEventListener('resize', resize, { passive: true });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { running = false; cancelAnimationFrame(frame); }
    else if (animate) { running = true; frame = requestAnimationFrame(loop); }
  });

  // Pre-compile every station shader up front so a first reveal never stalls.
  [crystal, rings, globe, candles].forEach((o) => (o.visible = true));
  renderer.compile(scene, camera);
  [crystal, rings, globe, candles].forEach((o) => (o.visible = false));

  requestAnimationFrame(() => canvas.parentElement.classList.add('is-ready'));

  if (animate) {
    renderFrame();
    frame = requestAnimationFrame(loop);
  } else {
    // reduced motion: settle a pleasing static frame, no loop
    coreUni.uTime.value = 2.0; partUni.uTime.value = 2.0;
    coreUni.uIntensity.value = 0.5;
    core.rotation.set(0.2, 0.6, 0);
    shell.rotation.copy(core.rotation);
    renderer.render(scene, camera);
  }
}

/* ---------------------------------------------------------------------------
   Boot
   ------------------------------------------------------------------------- */
function boot() {
  initMotion();

  const canvas = document.getElementById('living-canvas');
  if (!canvas) return;

  if (!webglSupported()) {
    document.documentElement.classList.add('no-webgl');
    return;
  }
  initScene(canvas, !PREFERS_REDUCED).catch((err) => {
    console.warn('[home] WebGL scene failed, using static fallback:', err);
    document.documentElement.classList.add('no-webgl');
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
