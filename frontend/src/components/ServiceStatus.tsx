import React, { useState, useEffect, useCallback, useRef } from 'react'
import { healthAPI } from '@/lib/api'
import { CheckCircle2, XCircle, Loader2, RefreshCw, AlertCircle, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ServiceHealth {
  status: 'healthy' | 'unhealthy' | 'degraded'
  message: string
}

interface HealthStatus {
  status: 'healthy' | 'unhealthy' | 'checking'
  services: Record<string, ServiceHealth>
  lastChecked?: Date
}

export default function ServiceStatus() {
  const [healthStatus, setHealthStatus] = useState<HealthStatus>({
    status: 'checking',
    services: {},
  })
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const checkFrontendHealth = useCallback((): ServiceHealth => {
    try {
      // Check localStorage availability
      try {
        const testKey = '__health_check__'
        localStorage.setItem(testKey, 'test')
        localStorage.removeItem(testKey)
      } catch (e) {
        return {
          status: 'degraded',
          message: 'LocalStorage not available (private browsing mode)',
        }
      }

      // Check sessionStorage availability
      try {
        const testKey = '__health_check__'
        sessionStorage.setItem(testKey, 'test')
        sessionStorage.removeItem(testKey)
      } catch (e) {
        return {
          status: 'degraded',
          message: 'SessionStorage not available',
        }
      }

      // Check if React is rendering properly
      if (!document || !window) {
        return {
          status: 'unhealthy',
          message: 'Browser APIs not available',
        }
      }

      return {
        status: 'healthy',
        message: 'Frontend is operational',
      }
    } catch (error) {
      return {
        status: 'unhealthy',
        message: `Frontend error: ${error instanceof Error ? error.message : 'Unknown error'}`,
      }
    }
  }, [])

  const checkHealth = useCallback(async (showLoading = false) => {
    if (showLoading) {
      setIsRefreshing(true)
    }
    
    try {
      const response = await healthAPI.getHealthStatus()
      
      // Add frontend health check
      const frontendHealth = checkFrontendHealth()
      const allServices = {
        ...response.services,
        frontend: frontendHealth,
      }

      // Determine overall status (frontend issues don't fail overall, but backend issues do)
      let overallStatus = response.status
      if (frontendHealth.status === 'unhealthy') {
        overallStatus = 'unhealthy'
      }

      setHealthStatus({
        status: overallStatus === 'healthy' ? 'healthy' : 'unhealthy',
        services: allServices,
        lastChecked: new Date(),
      })
    } catch (error) {
      // Even if backend fails, check frontend
      const frontendHealth = checkFrontendHealth()
      setHealthStatus({
        status: 'unhealthy',
        services: {
          frontend: frontendHealth,
          backend: {
            status: 'unhealthy',
            message: 'Failed to fetch health status',
          },
        },
        lastChecked: new Date(),
      })
    } finally {
      if (showLoading) {
        setIsRefreshing(false)
      }
    }
  }, [checkFrontendHealth])

  // Initial check and set up interval
  useEffect(() => {
    checkHealth()
    
    // Update every 1 minute (60000ms)
    const interval = setInterval(() => {
      checkHealth()
    }, 60000)

    return () => clearInterval(interval)
  }, [checkHealth])

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setDropdownOpen(false)
      }
    }

    if (dropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [dropdownOpen])

  const handleRefresh = (e: React.MouseEvent) => {
    e.stopPropagation()
    checkHealth(true)
  }

  const getOverallStatusIcon = () => {
    if (healthStatus.status === 'checking' || isRefreshing) {
      return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
    }
    if (healthStatus.status === 'healthy') {
      return <CheckCircle2 className="h-4 w-4 text-green-500" />
    }
    return <XCircle className="h-4 w-4 text-red-500" />
  }

  const getOverallStatusText = () => {
    if (healthStatus.status === 'checking' || isRefreshing) {
      return 'Checking...'
    }
    if (healthStatus.status === 'healthy') {
      return 'All Systems Operational'
    }
    return 'Service Issues Detected'
  }

  const getServiceStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy':
        return <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
      case 'unhealthy':
        return <XCircle className="h-3.5 w-3.5 text-red-500" />
      case 'degraded':
        return <AlertCircle className="h-3.5 w-3.5 text-yellow-500" />
      default:
        return <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
    }
  }

  const getServiceStatusColor = (status: string) => {
    switch (status) {
      case 'healthy':
        return 'text-green-500'
      case 'unhealthy':
        return 'text-red-500'
      case 'degraded':
        return 'text-yellow-500'
      default:
        return 'text-muted-foreground'
    }
  }

  const formatServiceName = (name: string) => {
    // Handle special cases for better formatting
    const nameMap: Record<string, string> = {
      'langfuse': 'Langfuse',
      'database': 'Database',
      'backend': 'Backend API',
      'cache': 'Cache',
      'frontend': 'Frontend',
      'temporal': 'Temporal',
    }
    return nameMap[name.toLowerCase()] || name.charAt(0).toUpperCase() + name.slice(1)
  }

  // Order services: frontend, backend, database, temporal, langfuse, cache, then others
  const getServiceOrder = (name: string): number => {
    const orderMap: Record<string, number> = {
      'frontend': 1,
      'backend': 2,
      'database': 3,
      'temporal': 4,
      'langfuse': 5,
      'cache': 6,
    }
    return orderMap[name.toLowerCase()] || 99
  }

  const serviceEntries = Object.entries(healthStatus.services).sort(([a], [b]) => {
    return getServiceOrder(a) - getServiceOrder(b)
  })

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setDropdownOpen(!dropdownOpen)}
        className={cn(
          "flex items-center gap-2 px-3 py-2 rounded-md",
          "hover:bg-accent transition-colors",
          "border border-border",
          "text-sm font-medium"
        )}
        title="View service status"
      >
        <div className="flex items-center gap-2">
          {getOverallStatusIcon()}
          <span className={cn(
            healthStatus.status === 'healthy' && !isRefreshing ? 'text-green-500' : '',
            healthStatus.status === 'unhealthy' && !isRefreshing ? 'text-red-500' : '',
            (healthStatus.status === 'checking' || isRefreshing) && 'text-muted-foreground'
          )}>
            {getOverallStatusText()}
          </span>
        </div>
        <ChevronDown 
          className={cn(
            "h-3.5 w-3.5 text-muted-foreground transition-transform",
            dropdownOpen && "rotate-180"
          )} 
        />
      </button>

      {/* Dropdown Menu */}
      {dropdownOpen && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setDropdownOpen(false)}
          />
          <div className="absolute top-full right-0 mt-1 w-72 bg-background border rounded-lg shadow-lg p-2 z-20">
            <div className="flex items-center justify-between mb-2 px-2 py-1">
              <span className="text-sm font-semibold">Service Status</span>
              <button
                onClick={handleRefresh}
                className="p-1 hover:bg-muted rounded-md transition-colors"
                title="Refresh status"
              >
                <RefreshCw 
                  className={cn(
                    "h-3.5 w-3.5 text-muted-foreground",
                    isRefreshing && "animate-spin"
                  )} 
                />
              </button>
            </div>
            
            {serviceEntries.length === 0 ? (
              <div className="px-2 py-3 text-sm text-muted-foreground text-center">
                No service data available
              </div>
            ) : (
              <div className="space-y-1">
                {serviceEntries.map(([serviceName, serviceHealth]) => (
                  <div
                    key={serviceName}
                    className="flex items-start gap-2 px-2 py-2 hover:bg-muted rounded-md transition-colors"
                  >
                    <div className="mt-0.5 flex-shrink-0">
                      {getServiceStatusIcon(serviceHealth.status)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">
                          {formatServiceName(serviceName)}
                        </span>
                        <span className={cn(
                          "text-xs font-medium",
                          getServiceStatusColor(serviceHealth.status)
                        )}>
                          {serviceHealth.status}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {serviceHealth.message}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {healthStatus.lastChecked && (
              <div className="mt-2 pt-2 border-t border-border">
                <p className="text-xs text-muted-foreground px-2">
                  Last checked: {healthStatus.lastChecked.toLocaleTimeString()}
                </p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
