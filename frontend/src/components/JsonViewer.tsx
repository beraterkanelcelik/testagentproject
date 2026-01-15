import React from 'react'
import ReactJson from '@microlink/react-json-view'

interface JsonViewerProps {
  data: any
  collapsed?: number | boolean
  className?: string
}

export default function JsonViewer({ 
  data, 
  collapsed = 2, 
  className = '' 
}: JsonViewerProps) {
  // Try to parse if it's a string
  let parsedData = data
  if (typeof data === 'string') {
    try {
      parsedData = JSON.parse(data)
    } catch {
      // If not valid JSON, return as-is
      parsedData = data
    }
  }

  // If it's not an object/array, show as plain text
  if (typeof parsedData !== 'object' || parsedData === null) {
    return (
      <div className={`text-xs font-mono bg-background/50 p-2 rounded ${className}`}>
        {String(parsedData)}
      </div>
    )
  }

  return (
    <div className={`json-viewer ${className}`}>
      <ReactJson
        src={parsedData}
        collapsed={collapsed}
        enableClipboard={false}
        displayDataTypes={false}
        displayObjectSize={false}
        theme="rjv-default"
        style={{
          backgroundColor: 'transparent',
          fontSize: '12px',
        }}
        iconStyle="triangle"
        indentWidth={2}
      />
    </div>
  )
}
