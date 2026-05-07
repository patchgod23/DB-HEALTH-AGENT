import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, Database, Server, CheckCircle2, AlertCircle, ChevronDown, ChevronRight, BrainCircuit } from 'lucide-react';
import { Route, Switch, useLocation } from 'wouter';

// Define types
type Severity = 'OK' | 'WARNING' | 'CRITICAL' | 'UNKNOWN';

interface ServerFleetData {
  id: string;
  host: string;
  database: string;
  status: Severity;
  latency_ms: number | null;
  last_scan: string;
}

interface CheckResult {
  check_name: string;
  severity: Severity;
  message: string;
  value: any;
  duration_ms: number;
}

interface ServerDetailData {
  state: {
    server_id: string;
    host: string;
    database: string;
    overall_severity: Severity;
    timestamp: string;
    checks: CheckResult[];
    recommended_actions?: string[];
  };
  ai_context?: {
    narrative: string;
    updated_at: string;
  };
}

function StatusBadge({ status }: { status: Severity }) {
  const cls = `badge badge-${status.toLowerCase()}`;
  return <span className={cls}>{status}</span>;
}

function getRelativeTime(timestamp: string) {
  const now = new Date();
  const then = new Date(timestamp);
  
  // Diff in seconds
  let diff = Math.floor((now.getTime() - then.getTime()) / 1000);
  
  // If we have a timezone skew (e.g. server in UTC, client in Local), 
  // we take the absolute diff or assume the smaller one if it's within a threshold.
  const absDiff = Math.abs(diff);
  
  // For the dashboard, if it's very small, it's "just now"
  if (absDiff < 60) return `${absDiff}s ago`;
  if (absDiff < 3600) return `${Math.floor(absDiff / 60)}m ago`;
  return `${Math.floor(absDiff / 3600)}h ago`;
}

function FleetOverview() {
  const [, setLocation] = useLocation();
  const { data, error, isLoading } = useQuery<{ fleet: ServerFleetData[] }>({
    queryKey: ['servers'],
    queryFn: () => fetch('/api/servers').then((res) => res.json())
  });

  if (isLoading) return <div className="text-muted font-mono">Loading telemetry...</div>;
  if (error) return <div className="badge badge-critical">API ERROR</div>;

  return (
    <div>
      <div className="table-container">
        <table className="fleet-table">
          <thead>
            <tr>
              <th style={{ width: '100px' }}>Status</th>
              <th>Server</th>
              <th>Database</th>
              <th>Latency</th>
              <th style={{ textAlign: 'right' }}>Last Scan</th>
            </tr>
          </thead>
          <tbody>
            {data?.fleet.map((srv) => (
              <tr key={srv.id} onClick={() => setLocation(`/server/${srv.id}`)}>
                <td><StatusBadge status={srv.status} /></td>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Server size={14} className="text-muted" />
                    <strong>{srv.id}</strong>
                  </div>
                </td>
                <td className="text-secondary">{srv.database}</td>
                <td className="text-muted font-mono">{srv.latency_ms ? `${srv.latency_ms.toFixed(0)}ms` : '-'}</td>
                <td className="text-muted font-mono" style={{ textAlign: 'right' }}>{getRelativeTime(srv.last_scan)}</td>
              </tr>
            ))}
            {data?.fleet.length === 0 && (
              <tr>
                <td colSpan={5} className="text-muted" style={{ textAlign: 'center' }}>No telemetry data.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ServerDetail({ params }: { params: { id: string } }) {
  const [, setLocation] = useLocation();
  const [showAI, setShowAI] = useState(true);
  const [chatMessage, setChatMessage] = useState('');
  const { id } = params;
  const [messages, setMessages] = useState<{role: 'user' | 'ai', text: string, execution?: any}[]>([]);
  const [isSending, setIsSending] = useState(false);

  const { data, isLoading, error } = useQuery<ServerDetailData>({
    queryKey: ['server', id],
    queryFn: () => fetch(`/api/servers/${id}`).then((res) => res.json())
  });

  if (isLoading) return <div className="text-muted font-mono">Loading telemetry...</div>;
  if (error || !data) return <div className="badge badge-critical">SERVER NOT FOUND</div>;

  const { state, ai_context } = data;

  const handleSendMessage = () => {
    if (!chatMessage || isSending) return;
    
    const userMsg = chatMessage;
    setMessages(prev => [...prev, { role: 'user', text: userMsg }]);
    setChatMessage('');
    setIsSending(true);

    fetch(`/api/chat?server_id=${id}&message=${encodeURIComponent(userMsg)}`, { method: 'POST' })
      .then(res => res.json())
      .then(data => {
        setMessages(prev => [...prev, { 
          role: 'ai', 
          text: data.response, 
          execution: data.executed ? data.execution_result : null 
        }]);
        setIsSending(false);
      })
      .catch(err => {
        setMessages(prev => [...prev, { role: 'ai', text: "Error de conexión con el Veterano." }]);
        setIsSending(false);
      });
  };

  return (
    <div className="detail-grid">
      <div className="detail-header">
        <button className="btn-back" onClick={() => setLocation('/')}>
          ← Back to Fleet
        </button>
        <div className="detail-header-info">
           <span className="text-muted font-mono" style={{ fontSize: '11px' }}>{getRelativeTime(state.timestamp)}</span>
           <StatusBadge status={state.overall_severity} />
        </div>
      </div>

      <header style={{ marginBottom: '20px' }}>
        <h1 style={{ fontSize: '20px', fontWeight: 600, wordBreak: 'break-all' }}>{state.server_id}</h1>
        <p className="text-secondary" style={{ fontSize: '12px' }}>{state.host} / {state.database}</p>
      </header>
      
      {state.recommended_actions && state.recommended_actions.length > 0 && (
        <section className="maintenance-box">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
            <AlertCircle size={18} color="var(--status-warning)" />
            <strong style={{ fontSize: '14px' }}>Mantenimiento Sugerido por el Agente:</strong>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {state.recommended_actions.map(action => (
              <div key={action} className="maintenance-item">
                <code style={{ fontSize: '12px' }}>{action}</code>
                <button 
                  className="btn-run"
                  onClick={() => {
                    if (confirm(`¿Estás seguro de ejecutar ${action} en ${state.database}?`)) {
                      fetch(`/api/maintenance/run?server_id=${state.server_id}&script_name=${action}`, { method: 'POST' })
                        .then(res => res.json())
                        .then(data => alert(data.message || data.error))
                        .catch(err => alert("Error: " + err));
                    }
                  }}
                >
                  Ejecutar ahora
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="detail-section">
        <h3 style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '12px', letterSpacing: '0.5px' }}>
          Health Checks
        </h3>
        {state.checks.map((check) => (
          <div key={check.check_name} className="check-item">
            {check.severity === 'OK' ? (
              <CheckCircle2 size={16} color="var(--status-ok)" style={{ flexShrink: 0 }} />
            ) : (
              <AlertCircle size={16} color={check.severity === 'CRITICAL' ? 'var(--status-critical)' : 'var(--status-warning)'} style={{ flexShrink: 0 }} />
            )}
            <div className="check-item-content">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontWeight: 600 }}>{check.check_name}</span>
                <span className="text-muted font-mono" style={{ fontSize: '10px' }}>{check.duration_ms.toFixed(0)}ms</span>
              </div>
              <p className="text-secondary" style={{ fontSize: '13px', marginTop: '2px' }}>{check.message}</p>
              {check.severity !== 'OK' && (
                <div className="evidence-block">
                  {JSON.stringify(check.value, null, 2)}
                </div>
              )}
            </div>
          </div>
        ))}
      </section>

      {/* Fase C: AI Narrative */}
      {ai_context && (
        <div className="ai-narrative-panel">
          <div 
            style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setShowAI(!showAI)}
          >
            <BrainCircuit size={16} color="#4ade80" />
            <span style={{ fontWeight: 600, fontSize: '13px', flex: 1 }}>AI Interpretation & Interactive Chat</span>
            {showAI ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </div>
          
          {showAI && (
            <div style={{ marginTop: '16px' }}>
              {/* Mensaje inicial de la IA (el diagnóstico cacheado) */}
              <div className="message-bubble message-ai" style={{ marginBottom: '20px', maxWidth: '100%' }}>
                {ai_context.narrative}
                <div style={{ marginTop: '8px', fontSize: '10px', opacity: 0.7 }}>
                  Último diagnóstico automático: {new Date(ai_context.updated_at).toLocaleString()}
                </div>
              </div>

              {/* Historial de conversación */}
              <div className="chat-messages">
                {messages.map((msg, idx) => (
                  <div key={idx} className={`message-bubble message-${msg.role}`}>
                    {msg.text}
                    {msg.execution && (
                      <div className={`execution-status ${msg.execution.success ? 'execution-success' : 'execution-error'}`}>
                        {msg.execution.success ? '✓ ' : '✗ '}
                        {msg.execution.message || msg.execution.error}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Input de Chat */}
              <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                <input 
                  type="text" 
                  className="chat-input"
                  placeholder="Habla con el Veterano o pide ejecutar un script..."
                  value={chatMessage}
                  onChange={(e) => setChatMessage(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                />
                <button 
                  className="btn-run" 
                  disabled={isSending || !chatMessage}
                  onClick={handleSendMessage}
                >
                  {isSending ? '...' : 'Enviar'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <div className="layout-shell">
      <header className="topbar">
        <Activity size={18} color="#4ade80" />
        <span>DB Health Console</span>
      </header>
      <main className="main-content">
        <Switch>
          <Route path="/" component={FleetOverview} />
          <Route path="/server/:id" component={ServerDetail} />
        </Switch>
      </main>
    </div>
  );
}
