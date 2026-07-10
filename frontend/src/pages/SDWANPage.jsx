import React, { useState, useEffect, useRef } from 'react';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import api from '@/lib/api';
import { toast } from 'sonner';
import SdwanOptimizerPanel from '@/components/peering/SdwanOptimizerPanel';
import {
  Activity, ChevronDown, RefreshCw,
  AlertCircle, Wifi, Zap, Globe, Server, Route, Plus,
  Trash2, Edit2, ToggleLeft, ToggleRight, Info, X
} from 'lucide-react';

/* ─── Tab config ─────────────────────────────────────────────── */
const TABS = [
  { id: 'failover', label: 'Failover Policies',    icon: Activity },
  { id: 'steering', label: 'BGP Content Steering', icon: Route },
  { id: 'guide',    label: 'Cara Penggunaan',      icon: Globe },
];

/* ─── BGP Content Steering Tab ─────────────────────────────── */
function BgpSteeringTab() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editPolicy, setEditPolicy] = useState(null);

  const { data: statusData, isLoading } = useQuery({
    queryKey: ['bgp_steering_status'],
    queryFn: async () => {
      const res = await api.get('/peering-eye/bgp-steering/status');
      return res.data;
    },
    refetchInterval: 30000,
  });

  const { data: catalog = [] } = useQuery({
    queryKey: ['bgp_steering_catalog'],
    queryFn: async () => {
      const res = await api.get('/peering-eye/bgp-steering/catalog');
      return res.data;
    },
    staleTime: Infinity,
  });

  const policies = statusData?.policies || [];
  const summary  = statusData?.summary  || {};

  const toggleMut = useMutation({
    mutationFn: (id) => api.post(`/peering-eye/bgp-steering/${id}/toggle`),
    onSuccess: (res) => {
      toast.success(res.data.message);
      queryClient.invalidateQueries(['bgp_steering_status']);
    },
    onError: (e) => toast.error(e.response?.data?.detail || 'Gagal toggle'),
  });

  const deleteMut = useMutation({
    mutationFn: (id) => api.delete(`/peering-eye/bgp-steering/${id}`),
    onSuccess: () => {
      toast.success('Kebijakan BGP Steering dihapus');
      queryClient.invalidateQueries(['bgp_steering_status']);
    },
    onError: (e) => toast.error(e.response?.data?.detail || 'Gagal hapus'),
  });

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold flex items-center gap-2">
            <Route className="w-5 h-5 text-violet-400" />
            BGP Content Steering
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Arahkan trafik platform tertentu (YouTube, Netflix, TikTok, dsb.) ke ISP/Gateway pilihan Anda — tanpa Mangle Rule.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => queryClient.invalidateQueries(['bgp_steering_status'])}
            className="p-2 rounded-md hover:bg-white/5 text-muted-foreground hover:text-foreground transition"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            onClick={() => { setEditPolicy(null); setShowModal(true); }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold transition"
          >
            <Plus className="w-4 h-4" /> Tambah Steering
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="rounded-xl border border-white/8 bg-card/60 p-4">
          <p className="text-[10px] text-muted-foreground uppercase tracking-widest">Total Policy</p>
          <p className="text-2xl font-bold tabular-nums mt-1">{summary.total_policies ?? 0}</p>
        </div>
        <div className="rounded-xl border border-violet-500/30 bg-violet-500/5 p-4">
          <p className="text-[10px] text-violet-400 uppercase tracking-widest">Aktif</p>
          <p className="text-2xl font-bold tabular-nums mt-1 text-violet-300">{summary.active_policies ?? 0}</p>
        </div>
        <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 p-4">
          <p className="text-[10px] text-blue-400 uppercase tracking-widest">Prefix Injected</p>
          <p className="text-2xl font-bold tabular-nums mt-1 text-blue-300">{summary.total_injected_prefixes ?? 0}</p>
        </div>
      </div>

      {/* Policies */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <div key={i} className="h-48 rounded-xl bg-white/5 animate-pulse" />)}
        </div>
      ) : policies.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-violet-500/10 flex items-center justify-center mb-4">
            <Route className="w-7 h-7 text-violet-400" />
          </div>
          <h3 className="font-semibold text-sm mb-1">Belum ada kebijakan BGP Steering</h3>
          <p className="text-xs text-muted-foreground max-w-xs mb-4">
            Klik tombol "Tambah Steering" untuk mengarahkan trafik platform tertentu ke ISP pilihan Anda.
          </p>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold transition"
          >
            <Plus className="w-4 h-4" /> Tambah Pertama
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {policies.map(policy => (
            <SteeringPolicyCard
              key={policy.id}
              policy={policy}
              onToggle={() => toggleMut.mutate(policy.id)}
              onEdit={() => { setEditPolicy(policy); setShowModal(true); }}
              onDelete={() => {
                if (window.confirm(`Hapus steering untuk ${policy.platform_name}?`)) {
                  deleteMut.mutate(policy.id);
                }
              }}
            />
          ))}
        </div>
      )}

      {/* Info box */}
      <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4">
        <div className="flex items-start gap-3">
          <Info className="w-4 h-4 text-violet-400 flex-shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="text-xs font-semibold text-violet-300">Cara Kerja BGP Content Steering</p>
            <p className="text-xs text-muted-foreground leading-relaxed">
              NOC-Sentinel akan membaca data domain aktif dari monitoring Peering Eye, me-resolve IP-nya, lalu menginjeksikannya ke MikroTik via iBGP dengan Next-Hop (Gateway) sesuai yang Anda atur.
              Daemon <code className="bg-white/10 px-1 rounded text-violet-300">sentinel_bgp.py</code> akan memperbarui injeksi setiap 5 menit secara otomatis.
              Tidak ada Mangle Rule yang dibuat — routing terjadi di level BGP secara native.
            </p>
          </div>
        </div>
      </div>

      {showModal && (
        <SteeringPolicyModal
          catalog={catalog}
          policy={editPolicy}
          onClose={() => { setShowModal(false); setEditPolicy(null); }}
          onSaved={() => {
            setShowModal(false);
            setEditPolicy(null);
            queryClient.invalidateQueries(['bgp_steering_status']);
          }}
        />
      )}
    </div>
  );
}

/* ─── Steering Policy Card ──────────────────────────────────── */
function SteeringPolicyCard({ policy, onToggle, onEdit, onDelete }) {
  const isActive    = policy.enabled && policy.active_prefix_count > 0;
  const borderColor = policy.enabled ? 'border-violet-500/40 hover:border-violet-400/60' : 'border-white/8';

  return (
    <div className={`group relative rounded-xl border ${borderColor} bg-card/60 backdrop-blur-sm p-5 transition-all duration-300 hover:shadow-[0_0_24px_-4px_rgba(139,92,246,0.2)]`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center text-xl"
            style={{ background: `${policy.color}22`, border: `1px solid ${policy.color}44` }}
          >
            {policy.icon}
          </div>
          <div>
            <p className="font-bold text-sm">{policy.platform_name}</p>
            {policy.isp_label && <p className="text-[10px] text-muted-foreground">{policy.isp_label}</p>}
          </div>
        </div>
        <button
          onClick={onToggle}
          className={`transition-colors ${policy.enabled ? 'text-violet-400 hover:text-violet-300' : 'text-muted-foreground hover:text-foreground'}`}
          title={policy.enabled ? 'Klik untuk nonaktifkan' : 'Klik untuk aktifkan'}
        >
          {policy.enabled ? <ToggleRight className="w-7 h-7" /> : <ToggleLeft className="w-7 h-7" />}
        </button>
      </div>

      <div className="bg-black/20 rounded-lg px-3 py-2 mb-3">
        <p className="text-[9px] text-muted-foreground uppercase tracking-widest mb-0.5">Gateway / Next-Hop</p>
        <p className="font-mono text-xs text-blue-300">{policy.gateway_ip || '—'}</p>
        {policy.target_peer && (
          <div className="mt-2 pt-2 border-t border-white/5">
            <p className="text-[9px] text-muted-foreground uppercase tracking-widest mb-0.5">Target BGP Peer</p>
            <p className="font-mono text-xs text-emerald-300">{policy.target_peer}</p>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">Prefix Aktif</span>
        <span className={`font-bold font-mono ${isActive ? 'text-violet-300' : 'text-muted-foreground'}`}>
          {policy.active_prefix_count ?? 0}
          {isActive && <span className="ml-1 text-[9px] font-normal text-violet-400/70">IP</span>}
        </span>
      </div>

      <div className="mt-2.5 flex items-center justify-between">
        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
          policy.enabled
            ? isActive
              ? 'bg-violet-500/15 text-violet-300 border-violet-500/30'
              : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
            : 'bg-white/5 text-muted-foreground border-white/10'
        }`}>
          {policy.enabled ? (isActive ? '● AKTIF' : '⏳ MENUNGGU DATA') : '○ NONAKTIF'}
        </span>
        <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={onEdit} className="p-1.5 rounded-md hover:bg-white/10 text-muted-foreground hover:text-foreground transition">
            <Edit2 className="w-3.5 h-3.5" />
          </button>
          <button onClick={onDelete} className="p-1.5 rounded-md hover:bg-red-500/20 text-muted-foreground hover:text-red-400 transition">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Steering Policy Modal ─────────────────────────────────── */
function SteeringPolicyModal({ catalog, policy, onClose, onSaved }) {
  const isEdit = !!policy;
  const [form, setForm] = useState({
    platform_name: policy?.platform_name || '',
    gateway_ip:    policy?.gateway_ip    || '',
    isp_label:     policy?.isp_label     || '',
    icon:           policy?.icon           || '🌐',
    color:          policy?.color          || '#6366f1',
    custom_prefixes: policy?.custom_prefixes?.join('\n') || '',
    description:    policy?.description    || '',
    enabled:        policy?.enabled !== false,
    target_peer:    policy?.target_peer    || '',
  });
  const [loading, setLoading] = useState(false);

  const { data: peersData } = useQuery({
    queryKey: ['bgp_peers_status_modal'],
    queryFn: async () => {
      const res = await api.get('/peering-eye/bgp/peers/status');
      return res.data;
    },
  });
  
  const peers = peersData?.peers || [];

  function selectCatalog(cat) {
    setForm(f => ({ ...f, platform_name: cat.name, icon: cat.icon, color: cat.color }));
  }

  async function handleSave() {
    if (!form.platform_name.trim()) return toast.error('Pilih platform terlebih dahulu');
    if (!form.gateway_ip.trim())    return toast.error('Isi IP Gateway / Next-Hop');
    setLoading(true);
    try {
      const payload = {
        ...form,
        custom_prefixes: form.custom_prefixes
          ? form.custom_prefixes.split('\n').map(s => s.trim()).filter(Boolean)
          : [],
      };
      if (isEdit) {
        await api.put(`/peering-eye/bgp-steering/${policy.id}`, payload);
        toast.success('Kebijakan diperbarui');
      } else {
        await api.post('/peering-eye/bgp-steering', payload);
        toast.success('Kebijakan BGP Steering berhasil dibuat');
      }
      onSaved();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal menyimpan');
    }
    setLoading(false);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg bg-card border border-border rounded-2xl shadow-2xl flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-5 border-b border-border">
          <div className="flex items-center gap-2">
            <Route className="w-5 h-5 text-violet-400" />
            <h3 className="font-bold text-base">{isEdit ? 'Edit' : 'Tambah'} BGP Content Steering</h3>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/10 transition">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="overflow-y-auto p-5 space-y-5 flex-1">
          {/* Platform picker */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-2">Platform</label>
            <div className="grid grid-cols-4 sm:grid-cols-5 gap-2">
              {catalog.map(cat => (
                <button
                  key={cat.name}
                  type="button"
                  onClick={() => selectCatalog(cat)}
                  disabled={isEdit}
                  className={`flex flex-col items-center gap-1 p-2 rounded-xl border transition ${
                    form.platform_name === cat.name
                      ? 'border-violet-500 bg-violet-500/15'
                      : 'border-white/10 hover:border-white/25 bg-white/3'
                  } ${isEdit ? 'opacity-50 cursor-not-allowed' : ''}`}
                  title={cat.name}
                >
                  <span className="text-lg">{cat.icon}</span>
                  <span className="text-[9px] text-muted-foreground truncate w-full text-center">{cat.name}</span>
                </button>
              ))}
            </div>
            {isEdit && <p className="text-[10px] text-muted-foreground mt-1">Platform tidak dapat diubah setelah dibuat.</p>}
          </div>

          {/* Gateway IP */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1.5">Gateway / Next-Hop IP *</label>
            <input
              type="text"
              value={form.gateway_ip}
              onChange={e => setForm(f => ({ ...f, gateway_ip: e.target.value }))}
              placeholder="Contoh: 192.168.1.1 atau 10.0.0.254"
              className="w-full px-3 py-2 bg-secondary border border-border rounded-lg text-sm font-mono focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
            <p className="text-[10px] text-muted-foreground mt-1">IP Gateway ISP yang akan menjadi Next-Hop untuk trafik platform ini.</p>
          </div>

          {/* ISP Label */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1.5">Label ISP (Opsional)</label>
            <input
              type="text"
              value={form.isp_label}
              onChange={e => setForm(f => ({ ...f, isp_label: e.target.value }))}
              placeholder="Contoh: ISP Dedicated Streaming"
              className="w-full px-3 py-2 bg-secondary border border-border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>

          {/* Target BGP Peer */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1.5">Target BGP Peer (Opsional)</label>
            <div className="relative">
              <select
                value={form.target_peer}
                onChange={e => setForm(f => ({ ...f, target_peer: e.target.value }))}
                className="w-full px-3 py-2 bg-secondary border border-border rounded-lg text-sm appearance-none focus:outline-none focus:ring-1 focus:ring-violet-500 pr-8"
              >
                <option value="">-- Semua Peer / Broadcast Global --</option>
                {peers.map(p => (
                  <option key={p.neighbor_ip} value={p.neighbor_ip}>
                    {p.neighbor_ip} {p.state === 'ESTABLISHED' ? '(ESTABLISHED)' : `(${p.state})`} - {p.device_name || 'Unknown'}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              Jika dipilih, policy ini akan dicatat / ditujukan hanya untuk BGP Peer ini.
            </p>
          </div>

          {/* Custom prefixes */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1.5">Custom Prefix (Opsional)</label>
            <textarea
              value={form.custom_prefixes}
              onChange={e => setForm(f => ({ ...f, custom_prefixes: e.target.value }))}
              placeholder={"Masukkan CIDR manual, satu per baris:\n203.0.113.0/24\n198.51.100.0/24"}
              rows={4}
              className="w-full px-3 py-2 bg-secondary border border-border rounded-lg text-sm font-mono focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
            />
            <p className="text-[10px] text-muted-foreground mt-1">
              Kosongkan jika ingin menggunakan IP yang di-resolve otomatis dari data monitoring Peering Eye.
              Isi jika Anda punya daftar CIDR spesifik dari ISP/CDN.
            </p>
          </div>

          {/* Enabled toggle */}
          <div className="flex items-center justify-between p-3 bg-secondary/50 rounded-lg">
            <div>
              <p className="text-sm font-medium">Aktifkan Sekarang</p>
              <p className="text-[10px] text-muted-foreground">Daemon akan mulai menginjeksi prefix pada siklus berikutnya (~5 menit)</p>
            </div>
            <button
              type="button"
              onClick={() => setForm(f => ({ ...f, enabled: !f.enabled }))}
              className={`transition-colors ${form.enabled ? 'text-violet-400' : 'text-muted-foreground'}`}
            >
              {form.enabled ? <ToggleRight className="w-8 h-8" /> : <ToggleLeft className="w-8 h-8" />}
            </button>
          </div>
        </div>

        <div className="flex justify-end gap-3 p-5 border-t border-border">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-border text-sm hover:bg-secondary/50 transition">Batal</button>
          <button
            onClick={handleSave}
            disabled={loading || !form.platform_name}
            className="px-5 py-2 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold transition disabled:opacity-50"
          >
            {loading ? 'Menyimpan...' : isEdit ? 'Simpan Perubahan' : 'Buat Steering'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Empty state ───────────────────────────────────────────── */
function EmptyState({ icon: Icon, title, desc }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mb-4">
        <Icon className="w-7 h-7 text-muted-foreground" />
      </div>
      <h3 className="font-semibold text-sm mb-1">{title}</h3>
      <p className="text-xs text-muted-foreground max-w-xs">{desc}</p>
    </div>
  );
}

/* ─── Stat card ─────────────────────────────────────────────── */
function StatCard({ label, value, icon: Icon, color = 'text-blue-400', sub }) {
  return (
    <div className="rounded-xl border border-white/8 bg-card/60 p-4 flex items-center gap-4">
      <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(255,255,255,0.04)' }}>
        <Icon className={`w-5 h-5 ${color}`} />
      </div>
      <div>
        <p className="text-[11px] text-muted-foreground">{label}</p>
        <p className="text-xl font-bold tabular-nums">{value}</p>
        {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
      </div>
    </div>
  );
}

/* ─── Main Page ─────────────────────────────────────────────── */
export default function SDWANPage() {
  const [activeTab, setActiveTab] = useState('failover');
  const [selectedDevice, setSelectedDevice] = useState('');
  const [deviceOpen, setDeviceOpen] = useState(false);
  const dropRef = useRef(null);

  const { data: devices = [] } = useQuery({
    queryKey: ['sdwan_device_list'],
    queryFn: async () => {
      const res = await api.get('/devices');
      return res.data;
    },
    refetchInterval: 60000,
  });

  const { data: sdwanPolicies = [] } = useQuery({
    queryKey: ['sdwan_policies_count'],
    queryFn: async () => {
      const res = await api.get('/sdwan/policies');
      return res.data;
    },
    refetchInterval: 60000,
  });

  const { data: activeOverrides = [] } = useQuery({
    queryKey: ['sdwan_overrides_count'],
    queryFn: async () => {
      const res = await api.get('/sdwan/active-overrides');
      return res.data;
    },
    refetchInterval: 10000,
  });

  const onlineCount = devices.filter(d => d.status === 'online').length;

  useEffect(() => {
    const handler = (e) => {
      if (dropRef.current && !dropRef.current.contains(e.target)) setDeviceOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const selectedDev = devices.find(d => d.id === selectedDevice);

  return (
    <div className="space-y-6">
      {/* ── Page header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Zap className="w-6 h-6 text-amber-400" /> Load Balance
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Manajemen jalur WAN, failover otomatis, dan BGP Content Steering.
          </p>
        </div>

        {/* Device filter */}
        <div className="relative" ref={dropRef}>
          <button
            onClick={() => setDeviceOpen(v => !v)}
            className="flex items-center gap-2 px-3 py-2 rounded-md border border-border bg-card text-sm hover:bg-secondary/50 transition min-w-[180px]"
          >
            <Server className="w-4 h-4 text-muted-foreground flex-shrink-0" />
            <span className="flex-1 text-left truncate">{selectedDev ? selectedDev.name : 'Semua Device'}</span>
            <ChevronDown className={`w-3.5 h-3.5 text-muted-foreground transition ${deviceOpen ? 'rotate-180' : ''}`} />
          </button>
          {deviceOpen && (
            <div className="absolute right-0 mt-1 w-56 bg-card border border-border rounded-lg shadow-xl z-50 overflow-hidden">
              <button
                onClick={() => { setSelectedDevice(''); setDeviceOpen(false); }}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-secondary/50 ${!selectedDevice ? 'text-primary font-semibold' : ''}`}
              >
                Semua Device
              </button>
              {devices.map(d => (
                <button
                  key={d.id}
                  onClick={() => { setSelectedDevice(d.id); setDeviceOpen(false); }}
                  className={`w-full text-left px-3 py-2 text-sm hover:bg-secondary/50 flex items-center justify-between ${selectedDevice === d.id ? 'text-primary font-semibold' : ''}`}
                >
                  <span className="truncate">{d.name}</span>
                  <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${d.status === 'online' ? 'bg-emerald-400' : 'bg-red-500'}`} />
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Stat strip ── */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <StatCard label="Device Online"    value={`${onlineCount}/${devices.length}`} icon={Wifi}         color="text-emerald-400" sub="Router aktif" />
        <StatCard label="Failover Policies" value={sdwanPolicies.length}               icon={Activity}     color="text-blue-400"    sub="Kebijakan routing" />
        <StatCard
          label="Aktif Failover"
          value={activeOverrides.length}
          icon={AlertCircle}
          color={activeOverrides.length > 0 ? 'text-amber-400' : 'text-emerald-400'}
          sub={activeOverrides.length > 0 ? 'Route sedang dialihkan' : 'Semua primary'}
        />
      </div>

      {/* ── Tab Bar ── */}
      <div className="relative">
        <div className="flex items-center gap-1 border-b border-border">
          {TABS.map(tab => {
            const Icon    = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors duration-150 ${
                  isActive ? 'text-foreground' : 'text-muted-foreground hover:text-foreground/70'
                }`}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                <span className="hidden sm:inline">{tab.label}</span>
                {tab.id === 'failover' && activeOverrides.length > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
                )}
                {isActive && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-full" />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Tab Content ── */}
      <div className="min-h-[400px]">
        {activeTab === 'failover' && <SdwanOptimizerPanel deviceId={selectedDevice} />}
        {activeTab === 'steering' && <BgpSteeringTab />}
        {activeTab === 'guide'    && <HowToUseTab />}
      </div>
    </div>
  );
}

/* ─── How To Use Tab ────────────────────────────────────────── */
function HowToUseTab() {
  return (
    <div className="space-y-6 pb-8">
      <div className="flex items-center gap-3 pb-3 border-b border-border">
        <Globe className="w-5 h-5 text-primary" />
        <div>
          <h2 className="text-base font-bold">Panduan Load Balance — BGP Content Steering</h2>
          <p className="text-xs text-muted-foreground mt-0.5">Panduan konfigurasi failover dan BGP Content Steering</p>
        </div>
      </div>

      <div className="rounded-xl border border-violet-500/40 bg-violet-500/5 p-5">
        <div className="flex items-center gap-2 mb-4">
          <Route className="w-5 h-5 text-violet-400" />
          <h3 className="font-bold text-sm text-violet-400">BGP Content Steering — Panduan Lengkap</h3>
        </div>
        <div className="space-y-3">
          {[
            { label: 'Apa itu BGP Content Steering?', text: 'Fitur ini memungkinkan NOC-Sentinel mengarahkan trafik platform tertentu (YouTube, Netflix, TikTok, dsb.) ke jalur ISP/Gateway tertentu pilihan Anda — menggunakan BGP route injection secara native. Tidak ada Mangle Rule yang dibuat, sehingga CPU MikroTik tetap ringan bahkan di trafik multi-Gigabit.' },
            { label: 'Prasyarat MikroTik', text: 'Router MikroTik harus dikonfigurasi sebagai BGP Neighbor dengan server NOC-Sentinel: /routing bgp neighbor add name=sentinel remote-address=[IP-Server] remote-as=65000 multihop=yes ttl=255. AS Number 65000 adalah AS lokal GoBGP pada server NOC-Sentinel (bisa disesuaikan di .env dengan LOCAL_AS).' },
            { label: 'Langkah 1 — Aktifkan iBGP Session', text: 'Pastikan sentinel-bgp.service berjalan di server NOC-Sentinel (cek di Peering Eye → BGP Status). Setelah session ESTABLISHED, server NOC-Sentinel siap menginjeksi route ke MikroTik.' },
            { label: 'Langkah 2 — Tambah Kebijakan Steering', text: 'Buka tab "BGP Content Steering" → klik "Tambah Steering" → pilih platform (contoh: Netflix) → isi IP Gateway ISP yang akan menjadi Next-Hop (contoh: 192.168.10.1 untuk ISP Dedicated Streaming) → klik "Buat Steering".' },
            { label: 'Langkah 3 — Aktifkan & Monitor', text: 'Toggle kebijakan ke posisi ON. Daemon sentinel_bgp.py akan secara otomatis me-resolve IP Netflix dari data monitoring Peering Eye, lalu menginjeksikannya ke tabel BGP MikroTik dengan next-hop ke ISP Dedicated Anda. Proses ini berlangsung dalam 5 menit setelah toggle.' },
            { label: 'Custom Prefix (Advanced)', text: 'Jika Anda memiliki daftar CIDR spesifik dari ISP atau CDN (contoh: 45.57.0.0/18 untuk Netflix), masukkan di field "Custom Prefix" satu per baris. Opsi ini lebih cepat dan akurat karena tidak perlu menunggu DNS resolve dari monitoring.' },
            { label: 'Monitoring & Verifikasi', text: 'Jumlah prefix yang aktif terlihat di setiap kartu kebijakan. Untuk verifikasi di MikroTik: /ip route print where comment~"sentinel" — route-route ini akan muncul dengan next-hop sesuai Gateway yang dikonfigurasi.' },
          ].map((item, i) => (
            <div key={i} className="flex gap-3">
              <span className="flex-shrink-0 mt-0.5 w-5 h-5 rounded-full bg-violet-500/20 flex items-center justify-center text-[10px] font-bold text-violet-300">{i + 1}</span>
              <div>
                <p className="text-xs font-semibold text-foreground">{item.label}</p>
                <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{item.text}</p>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 p-3 bg-black/20 rounded-lg border border-violet-500/20">
          <p className="text-[10px] font-mono text-violet-300 font-bold mb-1">Contoh Config MikroTik RouterOS:</p>
          <pre className="text-[10px] font-mono text-muted-foreground leading-relaxed whitespace-pre-wrap">{`/routing bgp neighbor
add name=noc-sentinel-bgp remote-address=<IP-Server-NOC> \\
    remote-as=65000 multihop=yes ttl=255 \\
    hold-time=90 keepalive-time=30 \\
    nexthop-choice=propagate \\
    comment="NOC-Sentinel BGP Content Steering"

/ip route
# Route-route akan otomatis muncul setelah BGP session ESTABLISHED`}</pre>
        </div>
      </div>
    </div>
  );
}
