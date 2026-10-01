import { useCallback, useEffect, useRef, useState } from 'react'
import { buildJobWsUrl, cancelJob, getJob } from '../api'
import type { JobStatus } from '../types'

/**
 * Follow a backend job (sync, dependency scan or bulk action) to completion.
 *
 * Jobs run on a worker thread in the FastAPI process, so their progress has
 * to be pulled. This follows WS /ws/jobs/{id} and falls back to polling
 * GET /api/jobs/{id} if the socket will not open, which is what happens
 * behind proxies that do not pass WebSockets through. Either way the log is
 * accumulated here: the server only sends lines the client has not seen.
 */
export interface UseJobResult {
  job: JobStatus | null
  log: string[]
  running: boolean
  watch: (jobId: string) => void
  stop: () => void
  clear: () => void
}

const POLL_MS = 700

export function useJob(onFinish?: (job: JobStatus) => void): UseJobResult {
  const [job, setJob] = useState<JobStatus | null>(null)
  const [log, setLog] = useState<string[]>([])

  const socket = useRef<WebSocket | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const seen = useRef(0)
  const finished = useRef(false)
  // Keeping the callback in a ref stops a new closure from restarting the watch.
  const onFinishRef = useRef(onFinish)
  onFinishRef.current = onFinish

  const teardown = useCallback(() => {
    if (socket.current) {
      socket.current.onclose = null
      socket.current.close()
      socket.current = null
    }
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  useEffect(() => teardown, [teardown])

  const apply = useCallback((next: JobStatus) => {
    setJob(next)
    if (next.log.length) {
      setLog((prev) => [...prev, ...next.log])
      seen.current = next.log_total
    }
    if (next.status !== 'running' && !finished.current) {
      finished.current = true
      teardown()
      onFinishRef.current?.(next)
    }
  }, [teardown])

  const poll = useCallback((jobId: string) => {
    getJob(jobId, seen.current)
      .then((next) => {
        apply(next)
        if (next.status === 'running') {
          timer.current = setTimeout(() => poll(jobId), POLL_MS)
        }
      })
      .catch((err) => {
        setJob((prev) =>
          prev
            ? { ...prev, status: 'error', error: err instanceof Error ? err.message : String(err) }
            : prev,
        )
      })
  }, [apply])

  const watch = useCallback((jobId: string) => {
    teardown()
    seen.current = 0
    finished.current = false
    setLog([])
    setJob(null)

    let opened = false
    try {
      const ws = new WebSocket(buildJobWsUrl(jobId))
      socket.current = ws
      ws.onopen = () => {
        opened = true
      }
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'job') apply(data as JobStatus)
        } catch {
          // a frame we do not understand is not worth failing the watch over
        }
      }
      ws.onerror = () => {
        if (!opened) poll(jobId)
      }
      ws.onclose = () => {
        socket.current = null
        if (!finished.current) poll(jobId)
      }
    } catch {
      poll(jobId)
    }
  }, [apply, poll, teardown])

  const stop = useCallback(() => {
    if (job && job.status === 'running') {
      cancelJob(job.id).catch(() => undefined)
    }
  }, [job])

  const clear = useCallback(() => {
    teardown()
    setJob(null)
    setLog([])
  }, [teardown])

  return { job, log, running: job?.status === 'running', watch, stop, clear }
}
