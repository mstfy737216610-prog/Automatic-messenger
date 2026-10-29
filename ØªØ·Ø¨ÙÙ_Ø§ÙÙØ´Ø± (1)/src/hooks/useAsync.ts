import { useCallback, useEffect, useRef, useState } from 'react'

export function useAsync<T>(loader: () => Promise<T>, dependencies: unknown[] = [], pollMs?: number) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const loaderRef = useRef(loader)
  const dependencyKey = JSON.stringify(dependencies)

  useEffect(() => { loaderRef.current = loader }, [loader])

  const reload = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      setData(await loaderRef.current())
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'تعذّر تحميل البيانات')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
    if (!pollMs) return
    const timer = window.setInterval(() => void reload(true), pollMs)
    return () => window.clearInterval(timer)
  }, [reload, pollMs, dependencyKey])

  return { data, setData, loading, error, reload }
}
