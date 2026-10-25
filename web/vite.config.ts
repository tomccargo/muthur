import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the API runs separately (uvicorn on 8580); in the container FastAPI serves dist/.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8580' } },
  build: { outDir: 'dist', emptyOutDir: true },
});
