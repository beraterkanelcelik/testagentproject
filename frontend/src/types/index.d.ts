/// <reference path="./react.d.ts" />
/// <reference path="./react-router-dom.d.ts" />
/// <reference path="./global.d.ts" />

// Ensure JSX namespace is available globally
declare global {
  namespace JSX {
    interface IntrinsicElements {
      [elemName: string]: any
    }
  }
}

export {}
