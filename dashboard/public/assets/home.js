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

  // Responsive placement of the core/camera
  const group = new THREE.Group();
  group.add(glow); group.add(core); group.add(shell);
  scene.add(group);
  let coreXTarget = 0, coreScaleTarget = 1, baseY = 0.18;
  function layout() {
    const w = window.innerWidth;
    if (w > 1080) { coreXTarget = 1.55; coreScaleTarget = 1.12; baseY = -0.15; }
    else if (w > 820) { coreXTarget = 0.95; coreScaleTarget = 0.96; baseY = 0.1; }
    else { coreXTarget = 0.1; coreScaleTarget = 0.66; baseY = 1.4; }
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

    // ease the core toward centre and let it sink as the visitor reaches the
    // closing, so headlines never sit on the hottest part of the glow
    const xNow = coreXTarget * (1 - scrollProg * 0.9);
    const yNow = baseY - scrollProg * scrollProg * 2.4;
    group.position.x += (xNow - group.position.x) * 0.06;
    group.position.y += (yNow - group.position.y) * 0.06;
    group.scale.setScalar(coreScaleTarget * (1 + scrollProg * 0.06));

    renderer.render(scene, camera);
  }

  let last = 0;
  function loop(t) {
    if (!running) return;
    frame = requestAnimationFrame(loop);
    // Frame-pace by scroll: full rate while the core is the hero, then ease off
    // to ~30fps once it sinks behind content. Motion speed is time-based, so
    // pacing changes density, not speed.
    const cap = scrollProg < 0.45 ? 0 : 33;
    if (t - last < cap) return;
    last = t;
    renderFrame();
  }

  window.addEventListener('resize', resize, { passive: true });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { running = false; cancelAnimationFrame(frame); }
    else if (animate) { running = true; last = 0; frame = requestAnimationFrame(loop); }
  });

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
