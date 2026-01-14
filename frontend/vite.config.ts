import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Plugin to suppress WebSocket connection errors when HMR is disabled
const suppressWebSocketErrors = () => {
  return {
    name: 'suppress-websocket-errors',
    transformIndexHtml(html: string) {
      // Inject script to suppress WebSocket errors before Vite client loads
      return html.replace(
        '<head>',
        `<head>
    <script>
      // Suppress Vite WebSocket connection errors (HMR is disabled)
      const originalConsoleError = console.error;
      console.error = function(...args) {
        const message = args[0];
        if (typeof message === 'string' && 
            (message.includes('WebSocket connection to') || 
             message.includes('setupWebSocket'))) {
          return; // Suppress Vite WebSocket errors
        }
        originalConsoleError.apply(console, args);
      };
    </script>`
      );
    },
  };
};

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), suppressWebSocketErrors()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    // Hot-reload disabled - restart container manually for code changes
    hmr: false, // Disable Hot Module Replacement
    // Completely disable file watching to save memory (HMR is disabled anyway)
    watch: null, // Disable file watching entirely
    // Disable automatic dependency optimization on startup
    warmup: {
      clientFiles: [], // Don't pre-warm client files
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    // Reduce memory usage during build
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: undefined, // Let Vite handle chunking automatically
      },
    },
  },
  // Optimize dependency pre-bundling to reduce memory usage
  optimizeDeps: {
    // Disable automatic discovery - only pre-bundle what's explicitly needed
    entries: ['src/main.tsx'],
    // Reduce concurrent processing
    force: false, // Don't force re-optimization
    // Include problematic packages that need proper handling
    include: ['@microlink/react-json-view'],
    // Reduce memory usage during optimization
    esbuildOptions: {
      // Limit concurrent operations
      target: 'es2020',
    },
  },
  // Reduce memory usage by limiting cache
  cacheDir: '.vite',
  // Disable source maps in dev to save memory (can enable if needed for debugging)
  esbuild: {
    sourcemap: false,
  },
})
