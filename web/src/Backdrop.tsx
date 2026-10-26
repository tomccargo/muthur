// The page's backdrop: slow amber smoke behind the panels (DESIGN.md §6, 0.37), in the manner of Playlist Parser's
// normal mode but written for muthur. WebGL, drawn at a third of the window's size and about 30 frames a second, on
// the low-power GPU. It stops while the page is hidden (another tab, a minimised window) and never runs when the
// system asks for reduced motion; then the page keeps its plain background.
import { useEffect, useRef } from 'react';
import { motionOn } from './motion';

const VERTEX = 'attribute vec2 corner; void main() { gl_Position = vec4(corner, 0.0, 1.0); }';
// Value noise in four rotated octaves, warped by itself twice: smoke that drifts and folds. Strongest at the top of
// the window, gone by the bottom, so it never sits behind long lists.
const FRAGMENT = `
precision mediump float;
uniform vec2 size; uniform float time; uniform vec3 ground; uniform vec3 ink; uniform float amount;
float grain(vec2 p) { p = fract(p * vec2(233.34, 851.73)); p += dot(p, p + 23.45); return fract(p.x * p.y); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(grain(i), grain(i + vec2(1.0, 0.0)), f.x), mix(grain(i + vec2(0.0, 1.0)), grain(i + vec2(1.0, 1.0)), f.x), f.y);
}
float layers(vec2 p) {
  float sum = 0.0, weight = 0.5; mat2 turn = mat2(0.8, 0.6, -0.6, 0.8);
  for (int i = 0; i < 4; i++) { sum += weight * noise(p); p = turn * p * 2.1; weight *= 0.5; }
  return sum;
}
void main() {
  vec2 uv = gl_FragCoord.xy / size;
  vec2 p = gl_FragCoord.xy / size.y * 1.4;
  float t = time * 0.04;
  vec2 warp = vec2(layers(p + vec2(t, -0.7 * t)), layers(p + vec2(-0.6 * t, t) + 4.1));
  float smoke = layers(p + 2.6 * warp + vec2(0.0, 0.5 * t));
  float glow = smoothstep(0.42, 0.92, smoke) * smoothstep(0.0, 1.0, uv.y);
  gl_FragColor = vec4(mix(ground, ink, glow * amount), 1.0);
}`;

// '#0e1210' → [r, g, b] in 0..1; null for anything else.
function rgb(value: string): [number, number, number] | null {
  const hex = value.trim().replace('#', '');
  return hex.length === 6 ? [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255) as [number, number, number] : null;
}

export function Backdrop() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !motionOn()) return undefined;
    const gl = canvas.getContext('webgl', { antialias: false, alpha: false, powerPreference: 'low-power' });
    if (!gl) return undefined;
    const shader = (type: number, source: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, source);
      gl.compileShader(s);
      return s;
    };
    const program = gl.createProgram()!;
    gl.attachShader(program, shader(gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(program, shader(gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return undefined;
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);  // one triangle over the screen
    const corner = gl.getAttribLocation(program, 'corner');
    gl.enableVertexAttribArray(corner);
    gl.vertexAttribPointer(corner, 2, gl.FLOAT, false, 0, 0);
    const at = (name: string) => gl.getUniformLocation(program, name);
    const [size, time, ground, ink, amount] = ['size', 'time', 'ground', 'ink', 'amount'].map(at);

    let colours = { ground: [0.05, 0.07, 0.06], ink: [0.94, 0.66, 0.36], amount: 0.4 };
    const readTheme = () => {
      const css = getComputedStyle(document.documentElement);
      const g = rgb(css.getPropertyValue('--bg')) ?? colours.ground;
      const light = (g[0] + g[1] + g[2]) / 3 > 0.5;
      colours = { ground: g, ink: rgb(css.getPropertyValue('--accent')) ?? colours.ink, amount: light ? 0.28 : 0.4 };
      canvas.dataset.on = 'true';
    };
    readTheme();

    const start = performance.now();
    let raf = 0;
    let last = 0;
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (now - last < 33) return;  // ~30 frames a second: plenty for something this slow
      last = now;
      const w = Math.max(1, Math.round(innerWidth / 3));
      const h = Math.max(1, Math.round(innerHeight / 3));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
      gl.uniform2f(size, w, h);
      gl.uniform1f(time, (now - start) / 1000);
      gl.uniform3fv(ground, colours.ground);
      gl.uniform3fv(ink, colours.ink);
      gl.uniform1f(amount, colours.amount);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    const run = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) raf = requestAnimationFrame(frame);  // a hidden page draws nothing at all
    };
    const themes = new MutationObserver(readTheme);
    themes.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const scheme = matchMedia('(prefers-color-scheme: light)');
    scheme.addEventListener('change', readTheme);
    document.addEventListener('visibilitychange', run);
    run();
    return () => {
      cancelAnimationFrame(raf);
      themes.disconnect();
      scheme.removeEventListener('change', readTheme);
      document.removeEventListener('visibilitychange', run);
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    };
  }, []);
  return <canvas ref={ref} className="backdrop" aria-hidden="true" />;
}
