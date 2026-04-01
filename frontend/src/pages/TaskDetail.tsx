import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { approveTask, rejectTask, resubmitTask, retryTask, getTask } from '../api'
import Nav from '../components/Nav'
import ResearchView from '../components/ResearchView'
import StateBadge from '../components/StateBadge'
import type { TaskOut } from '../types'

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>()
  const [task, setTask] = useState<TaskOut | null>(null)
  const [error, setError] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [acting, setActing] = useState(false)
  const [resubmitting, setResubmitting] = useState(false)
  const [resubmitFields, setResubmitFields] = useState<{
    feature_name: string; description: string; repo: string;
    branch_from: string; additional_context: string;
  } | null>(null)
  const role = localStorage.getItem('role') ?? 'member'
  const isAdmin = role === 'admin'
  const currentUserId = localStorage.getItem('user_id')

  const load = useCallback(() => {
    if (!id) return
    getTask(id).then(setTask).catch(e => setError(String(e)))
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!task) return
    if (task.state === 'submitted' || task.state === 'researching') {
      const timer = setInterval(load, 3000)
      return () => clearInterval(timer)
    }
  }, [task?.state, load])

  async function handleApprove() {
    if (!id) return
    setActing(true)
    try {
      setTask(await approveTask(id))
    } catch (e) {
      setError(String(e))
    } finally {
      setActing(false)
    }
  }

  async function handleReject() {
    if (!id) return
    setActing(true)
    try {
      setTask(await rejectTask(id, rejectReason || undefined))
      setRejecting(false)
    } catch (e) {
      setError(String(e))
    } finally {
      setActing(false)
    }
  }

  if (!task && !error) return <><Nav /><div style={{ padding: 32 }}>Loading…</div></>
  if (error && !task) return <><Nav /><div style={{ padding: 32, color: '#dc2626' }}>{error}</div></>
  if (!task) return null

  return (
    <>
      <Nav />
      <div style={{ maxWidth: 800, margin: '32px auto', padding: '0 16px' }}>
        {/* Header */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <h2 style={{ margin: 0, fontSize: 22 }}>{task.feature_name}</h2>
            <StateBadge state={task.state} />
          </div>
          <div style={{ fontSize: 13, color: '#6b7280', display: 'flex', gap: 16 }}>
            <span>Repo: <code>{task.repo}</code></span>
            <span>Branch: <code>{task.branch_from}</code></span>
            <span>Submitted: {new Date(task.created_at).toLocaleString()}</span>
          </div>
        </div>

        {/* State-dependent content */}
        <div style={{ background: '#fff', borderRadius: 8, padding: 24, boxShadow: '0 2px 8px rgba(0,0,0,.08)' }}>
          {(task.state === 'submitted' || task.state === 'researching') && (() => {
            const STEP_LABELS: Record<string, string> = {
              task_created: 'Queued…',
              task_retried: 'Queued…',
              task_resubmitted: 'Queued…',
              research_started: 'Starting research…',
              querying_codebase: 'Querying codebase…',
              analyzing: 'Analyzing with Claude…',
            }
            const latest = [...task.logs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0]
            const label = (latest && STEP_LABELS[latest.event]) ?? 'Analyzing codebase…'
            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, color: '#6b7280', padding: '24px 0' }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  style={{ animation: 'spin 1s linear infinite' }}>
                  <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>
                <span>{label}</span>
                <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
              </div>
            )
          })()}

          {task.state === 'failed' && (
            <div>
              <div style={{ color: '#dc2626', marginBottom: 12 }}>
                <strong>Error:</strong> {task.error_message ?? 'Unknown error'}
              </div>
              <button
                onClick={async () => {
                  if (!id) return
                  setActing(true)
                  try { setTask(await retryTask(id)) }
                  catch (e) { setError(String(e)) }
                  finally { setActing(false) }
                }}
                disabled={acting}
                style={{
                  padding: '8px 20px', borderRadius: 4, background: '#111', color: '#fff',
                  border: 'none', fontSize: 14, fontWeight: 500, opacity: acting ? 0.5 : 1,
                }}
              >
                {acting ? 'Retrying…' : 'Retry'}
              </button>
            </div>
          )}

          {task.state === 'rejected' && (
            <div>
              <div style={{
                display: 'inline-block', marginBottom: 16, padding: '4px 12px', borderRadius: 4,
                background: '#fee2e2', color: '#dc2626', fontSize: 13, fontWeight: 600,
              }}>
                ✗ Rejected
              </div>
              {(isAdmin || currentUserId === task.submitter_id) && (
                resubmitting ? (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <input
                        value={resubmitFields?.feature_name ?? ''}
                        onChange={e => setResubmitFields(f => f ? { ...f, feature_name: e.target.value } : f)}
                        placeholder="Feature name"
                        style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
                      />
                      <textarea
                        value={resubmitFields?.description ?? ''}
                        onChange={e => setResubmitFields(f => f ? { ...f, description: e.target.value } : f)}
                        placeholder="Description"
                        rows={3}
                        style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
                      />
                      <input
                        value={resubmitFields?.repo ?? ''}
                        onChange={e => setResubmitFields(f => f ? { ...f, repo: e.target.value } : f)}
                        placeholder="Repo"
                        style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
                      />
                      <input
                        value={resubmitFields?.branch_from ?? ''}
                        onChange={e => setResubmitFields(f => f ? { ...f, branch_from: e.target.value } : f)}
                        placeholder="Branch"
                        style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
                      />
                      <textarea
                        value={resubmitFields?.additional_context ?? ''}
                        onChange={e => setResubmitFields(f => f ? { ...f, additional_context: e.target.value } : f)}
                        placeholder="Additional context (one item per line)"
                        rows={3}
                        style={{ padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14 }}
                      />
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                      <button
                        onClick={async () => {
                          if (!id || !resubmitFields) return
                          if (!resubmitFields.feature_name.trim() || !resubmitFields.description.trim() ||
                              !resubmitFields.repo.trim() || !resubmitFields.branch_from.trim()) {
                            setError('Feature name, description, repo, and branch are required.')
                            return
                          }
                          setError('')
                          setActing(true)
                          try {
                            const fields = {
                              feature_name: resubmitFields.feature_name || undefined,
                              description: resubmitFields.description || undefined,
                              repo: resubmitFields.repo || undefined,
                              branch_from: resubmitFields.branch_from || undefined,
                              additional_context: resubmitFields.additional_context
                                ? resubmitFields.additional_context.split('\n').map(s => s.trim()).filter(Boolean)
                                : undefined,
                            }
                            setTask(await resubmitTask(id, fields))
                            setResubmitting(false)
                            setResubmitFields(null)
                          } catch (e) {
                            setError(String(e))
                          } finally {
                            setActing(false)
                          }
                        }}
                        disabled={acting}
                        style={{
                          padding: '8px 20px', borderRadius: 4, background: '#111', color: '#fff',
                          border: 'none', fontSize: 14, fontWeight: 500, opacity: acting ? 0.5 : 1,
                        }}
                      >
                        {acting ? 'Resubmitting…' : 'Resubmit'}
                      </button>
                      <button
                        onClick={() => { setResubmitting(false); setResubmitFields(null) }}
                        style={{
                          padding: '8px 16px', borderRadius: 4, background: '#f3f4f6',
                          color: '#111', border: '1px solid #d1d5db', fontSize: 14,
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ marginTop: 8 }}>
                    <button
                      onClick={() => {
                        setResubmitting(true)
                        setResubmitFields({
                          feature_name: task.feature_name,
                          description: task.description,
                          repo: task.repo,
                          branch_from: task.branch_from,
                          additional_context: (task.additional_context ?? []).join('\n'),
                        })
                      }}
                      style={{
                        padding: '8px 20px', borderRadius: 4, background: '#fff', color: '#111',
                        border: '1px solid #d1d5db', fontSize: 14, fontWeight: 500,
                      }}
                    >
                      Edit &amp; Resubmit
                    </button>
                  </div>
                )
              )}
            </div>
          )}

          {task.research && (
            <>
              {task.state === 'approved' && (
                <div style={{
                  display: 'inline-block', marginBottom: 16, padding: '4px 12px', borderRadius: 4,
                  background: '#dcfce7', color: '#16a34a', fontSize: 13, fontWeight: 600,
                }}>
                  ✓ Approved
                </div>
              )}
              <ResearchView research={task.research} />
              {task.state === 'researched' && isAdmin && (
                <div style={{ marginTop: 24, display: 'flex', gap: 12, flexDirection: 'column', alignItems: 'flex-start' }}>
                  {rejecting ? (
                    <div style={{ width: '100%' }}>
                      <textarea
                        value={rejectReason}
                        onChange={e => setRejectReason(e.target.value)}
                        placeholder="Reason for rejection (optional)"
                        rows={3}
                        style={{ width: '100%', padding: '8px 12px', borderRadius: 4, border: '1px solid #d1d5db', fontSize: 14, marginBottom: 8 }}
                      />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button onClick={handleReject} disabled={acting} style={{
                          padding: '8px 16px', borderRadius: 4, background: '#dc2626', color: '#fff',
                          border: 'none', fontSize: 14, fontWeight: 500, opacity: acting ? 0.5 : 1,
                        }}>
                          {acting ? 'Rejecting…' : 'Confirm Reject'}
                        </button>
                        <button onClick={() => setRejecting(false)} style={{
                          padding: '8px 16px', borderRadius: 4, background: '#f3f4f6',
                          color: '#111', border: '1px solid #d1d5db', fontSize: 14,
                        }}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button onClick={handleApprove} disabled={acting} style={{
                        padding: '8px 20px', borderRadius: 4, background: '#16a34a', color: '#fff',
                        border: 'none', fontSize: 14, fontWeight: 500, opacity: acting ? 0.5 : 1,
                      }}>
                        {acting ? '…' : 'Approve'}
                      </button>
                      <button onClick={() => setRejecting(true)} style={{
                        padding: '8px 20px', borderRadius: 4, background: '#fff', color: '#dc2626',
                        border: '1px solid #dc2626', fontSize: 14, fontWeight: 500,
                      }}>
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  )
}
