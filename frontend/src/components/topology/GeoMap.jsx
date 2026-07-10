/**
 * TopologyPage — Geographic Network Map
 * - Peta OpenStreetMap (dark tile dari CartoDB) via Leaflet CDN
 * - Device sebagai marker yang bisa di-drag ke posisi fisik
 * - Posisi tersimpan ke MongoDB via PATCH /devices/{id}/location
 * - ARP link = garis antar device (toggle on/off)
 * - Popup detail: CPU, memory, ping, uptime, DL/UL
 * - Mode lock untuk presentasi
 */
import { useState, useEffect, useRef, useCallback } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  RefreshCw, Lock, Unlock, GitBranch, Link, Wifi, WifiOff,
  Cpu, HardDrive, Activity, Clock, Network, ChevronUp, ChevronDown,
  MapPin, LocateFixed, Layers, Info, Plus, X, Trash2
} from "lucide-react";

// ——— Leaflet global (loaded via CDN in index.html) ————————————————————————
const L = window.L;

// ——— Constants ————————————————————————————————————————————————————————————
// Default center: Jambi, Indonesia
const DEFAULT_CENTER = [-1.6101, 103.6131];
const DEFAULT_ZOOM   = 10;

// Warna per status device
const STATUS_COLORS = {
  online:  { fill: "#22c55e", border: "#16a34a", glow: "0 0 16px #22c55e88" },
  offline: { fill: "#ef4444", border: "#b91c1c", glow: "0 0 16px #ef444488" },
  unknown: { fill: "#6b7280", border: "#4b5563", glow: "none" },
  warning: { fill: "#eab308", border: "#ca8a04", glow: "0 0 14px #eab30888" },
};

// ——— Helper: buat SVG marker custom ———————————————————————————————————————
function makeIcon(status, selected = false) {
  const c = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  const size = selected ? 22 : 18;
  const ring = selected ? `<circle cx="20" cy="20" r="19" fill="none" stroke="${c.fill}" stroke-width="2" opacity="0.5"/>` : "";
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 50" width="${size*2}" height="${size*2.5}">
      ${ring}
      <circle cx="20" cy="20" r="14" fill="${c.fill}" stroke="${c.border}" stroke-width="2.5"/>
      <circle cx="20" cy="20" r="6"  fill="white" opacity="0.9"/>
      <polygon points="14,33 20,46 26,33" fill="${c.fill}"/>
    </svg>
  `;
  return L.divIcon({
    html: svg,
    className: "",
    iconSize:   [size*2,   size*2.5],
    iconAnchor: [size,     size*2.5 - 4],
    popupAnchor:[0,        -(size*2)],
  });
}

// ——— Helper: format bandwidth —————————————————————————————————————————————
function fmtBw(mbps) {
  if (mbps == null || mbps === 0) return "-";
  if (mbps >= 1000) return `${(mbps/1000).toFixed(2)} Gbps`;
  if (mbps >= 1)    return `${mbps.toFixed(1)} Mbps`;
  return `${(mbps*1000).toFixed(0)} Kbps`;
}

// ——— Popup HTML builder ———————————————————————————————————————————————————
function buildPopupHTML(d) {
  const statusColor = d.status === "online" ? "#22c55e" : d.status === "offline" ? "#ef4444" : "#6b7280";
  const statusLabel = (d.status || "unknown").toUpperCase();
  const cpu    = d.cpu_load    != null ? `${d.cpu_load}%`    : "-";
  const mem    = d.memory_usage != null ? `${d.memory_usage}%` : "-";
  const ping   = d.ping_ms     != null ? `${d.ping_ms} ms`   : "-";
  const dl     = fmtBw(d.download_mbps);
  const ul     = fmtBw(d.upload_mbps);
  const uptime = d.uptime || "-";
  const loc    = d.location_name ? `<div style="color:#94a3b8;font-size:10px;margin-top:2px">📍 ${d.location_name}</div>` : "";

  return `
    <div style="font-family:'Inter',sans-serif;min-width:200px;max-width:240px;color:#e2e8f0;background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:0;overflow:hidden">
      <div style="background:#1e293b;padding:10px 12px;display:flex;align-items:center;justify-content:space-between">
        <div>
          <div style="font-weight:700;font-size:13px;color:#f8fafc">${d.identity || d.name}</div>
          <div style="font-size:10px;color:#64748b;font-family:'IBM Plex Mono','Courier New',monospace">${d.ip_address || ""}</div>
          ${loc}
        </div>
        <span style="background:${statusColor}22;color:${statusColor};border:1px solid ${statusColor}44;border-radius:999px;font-size:9px;font-weight:700;padding:2px 8px">${statusLabel}</span>
      </div>
      <div style="padding:10px 12px;display:grid;grid-template-columns:1fr 1fr;gap:6px">
        <div style="background:#1e293b50;border-radius:6px;padding:6px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.05em">CPU</div>
          <div style="font-size:14px;font-weight:700;color:${parseInt(cpu)>80?"#ef4444":parseInt(cpu)>60?"#eab308":"#22c55e"}">${cpu}</div>
        </div>
        <div style="background:#1e293b50;border-radius:6px;padding:6px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Memory</div>
          <div style="font-size:14px;font-weight:700;color:${parseInt(mem)>85?"#ef4444":parseInt(mem)>70?"#eab308":"#3b82f6"}">${mem}</div>
        </div>
        <div style="background:#1e293b50;border-radius:6px;padding:6px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Ping</div>
          <div style="font-size:13px;font-weight:600;color:#a78bfa">${ping}</div>
        </div>
        <div style="background:#1e293b50;border-radius:6px;padding:6px;text-align:center">
          <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Uptime</div>
          <div style="font-size:10px;font-weight:600;color:#94a3b8;word-break:break-all">${uptime}</div>
        </div>
      </div>
      <div style="padding:0 12px 10px 12px;display:flex;gap:8px">
        <div style="flex:1;background:#1e3a5f30;border:1px solid #3b82f620;border-radius:6px;padding:5px;text-align:center">
          <div style="font-size:9px;color:#60a5fa">&#8595; DL</div>
          <div style="font-size:11px;font-weight:700;color:#93c5fd">${dl}</div>
        </div>
        <div style="flex:1;background:#14532d30;border:1px solid #22c55e20;border-radius:6px;padding:5px;text-align:center">
          <div style="font-size:9px;color:#4ade80">&#8593; UL</div>
          <div style="font-size:11px;font-weight:700;color:#86efac">${ul}</div>
        </div>
      </div>
      ${d.model ? `<div style="padding:0 12px 8px;font-size:10px;color:#475569">${d.model}${d.ros_version?" · v"+d.ros_version:""}</div>` : ""}
    </div>
  `;
}

// ——— Main Component ———————————————————————————————————————————————————————
export default function GeoMap() {
  const mapRef      = useRef(null);  // DOM element
  const leafletRef  = useRef(null);  // Leaflet map instance
  const markersRef  = useRef({});    // { deviceId: L.Marker }
  const polylinesRef= useRef([]);    // ARP links

  const [devices,     setDevices]     = useState([]);
  const [edges,       setEdges]       = useState([]);
  const [stats,       setStats]       = useState(null);
  const [loading,     setLoading]     = useState(false);
  const [locked,      setLocked]      = useState(false);  // lock drag mode
  const [showLinks,   setShowLinks]   = useState(true);   // toggle ARP lines
  const [filter,      setFilter]      = useState("all");  // all | online | offline
  const [savingId,    setSavingId]    = useState(null);   // device being saved
  const [unplaced,    setUnplaced]    = useState([]);     // devices belum ada lat/lng
  const [showUnplaced,setShowUnplaced]= useState(false);
  const [showAddModal, setShowAddModal] = useState(false);

  // ——— Fetch topology data —————————————————————————————————————————————————
  const fetchTopology = useCallback(async () => {
    setLoading(true);
    try {
      const [wallRes, topoRes] = await Promise.all([
        api.get("/wallboard/status"),
        api.get("/topology"),
      ]);
      const devs = wallRes.data.devices || [];
      const topo = topoRes.data;
      setDevices(devs);
      setEdges(topo.edges || []);
      setStats(wallRes.data.summary || topo.stats || null);
      setUnplaced(devs.filter(d => d.lat == null || d.lng == null));
    } catch (e) {
      toast.error("Gagal memuat data topology: " + (e.response?.data?.detail || e.message));
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchTopology(); }, [fetchTopology]);

  // ——— Init Leaflet map ————————————————————————————————————————————————————
  useEffect(() => {
    if (!mapRef.current || leafletRef.current || !L) return;

    const map = L.map(mapRef.current, {
      center:     DEFAULT_CENTER,
      zoom:       DEFAULT_ZOOM,
      zoomControl: false,
      attributionControl: false,
    });

    L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      {
        subdomains:  "abcd",
        maxZoom:     20,
        attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }
    ).addTo(map);

    L.control.zoom({ position: "bottomleft" }).addTo(map);
    L.control.attribution({ position: "bottomright", prefix: false }).addTo(map);

    leafletRef.current = map;

    return () => {
      map.remove();
      leafletRef.current = null;
      markersRef.current = {};
      polylinesRef.current = [];
    };
  }, []);

  // ——— Save device location ke backend —————————————————————————————————————
  const saveLocation = useCallback(async (deviceId, lat, lng) => {
    setSavingId(deviceId);
    try {
      await api.patch(`/devices/${deviceId}/location`, { lat, lng });
      toast.success("📍 Posisi tersimpan", { duration: 2000 });
      setUnplaced(prev => prev.filter(d => d.id !== deviceId));
    } catch (e) {
      toast.error("Gagal simpan posisi: " + (e.response?.data?.detail || e.message));
    }
    setSavingId(null);
  }, []);

  // ——— Render markers ——————————————————————————————————————————————————————
  useEffect(() => {
    const map = leafletRef.current;
    if (!map || !L || devices.length === 0) return;

    Object.values(markersRef.current).forEach(m => m.remove());
    markersRef.current = {};

    const visible = filter === "all" ? devices : devices.filter(d => d.status === filter);
    const withCoords = visible.filter(d => d.lat != null && d.lng != null);

    visible.forEach((d, idx) => {
      const hasCoords = d.lat != null && d.lng != null;
      const angle = (idx / Math.max(visible.length, 1)) * 2 * Math.PI;
      const r = 0.05 + (idx % 3) * 0.02;
      const lat = hasCoords ? d.lat : DEFAULT_CENTER[0] + r * Math.sin(angle);
      const lng = hasCoords ? d.lng : DEFAULT_CENTER[1] + r * Math.cos(angle);

      const status = d.status || "unknown";
      const icon   = makeIcon(status);

      const marker = L.marker([lat, lng], {
        draggable: !locked,
        icon,
        title: d.identity || d.name,
      });

      marker.bindPopup(buildPopupHTML(d), {
        maxWidth: 260,
        className: "noc-popup",
      });

      marker.on("dragend", (e) => {
        const { lat: newLat, lng: newLng } = e.target.getLatLng();
        saveLocation(d.id, newLat, newLng);
      });

      marker.on("click", () => marker.openPopup());

      marker.addTo(map);
      markersRef.current[d.id] = marker;

      marker.bindTooltip(d.identity || d.name, {
        permanent:  true,
        direction:  "top",
        offset:     [0, -36],
        className:  "noc-label",
        opacity:    0.95,
      });
    });

    if (withCoords.length >= 2) {
      const latlngs = withCoords.map(d => [d.lat, d.lng]);
      try {
        map.fitBounds(L.latLngBounds(latlngs), { padding: [50, 50], maxZoom: 13 });
      } catch (_) {}
    }

  }, [devices, filter, locked, saveLocation]);

  // ——— Update drag mode saat lock toggle ———————————————————————————————————
  useEffect(() => {
    Object.values(markersRef.current).forEach(m => {
      try {
        if (locked) m.dragging.disable();
        else        m.dragging.enable();
      } catch (_) {}
    });
    if (!locked) toast.info('Mode edit aktif - drag marker ke lokasi fisik', { duration: 3000 });
  }, [locked]);

  // ——— Render ARP polylines ————————————————————————————————————————————————
  useEffect(() => {
    const map = leafletRef.current;
    if (!map || !L) return;

    polylinesRef.current.forEach(l => l.remove());
    polylinesRef.current = [];

    if (!showLinks) return;

    edges.forEach(e => {
      const srcMarker = markersRef.current[e.source];
      const dstMarker = markersRef.current[e.target];
      if (!srcMarker || !dstMarker) return;
      const line = L.polyline(
        [srcMarker.getLatLng(), dstMarker.getLatLng()],
        { color: "#3b82f6", weight: 1.5, opacity: 0.45, dashArray: "6,4" }
      ).addTo(map);
      polylinesRef.current.push(line);
    });
  }, [edges, showLinks, devices]);

  const resetView = () => {
    leafletRef.current?.setView(DEFAULT_CENTER, DEFAULT_ZOOM, { animate: true });
  };

  const fitAll = () => {
    const latlngs = Object.values(markersRef.current).map(m => m.getLatLng());
    if (latlngs.length === 0) return;
    try {
      leafletRef.current?.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40], maxZoom: 14 });
    } catch (_) {}
  };

  const online  = devices.filter(d => d.status === "online").length;
  const offline = devices.filter(d => d.status === "offline").length;
  const warning = devices.filter(d => d.alert_level === "warning").length;

  useEffect(() => {
    const styleId = "noc-leaflet-style";
    if (document.getElementById(styleId)) return;
    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
      .noc-popup .leaflet-popup-content-wrapper {
        background: transparent !important;
        border: none !important;
        box-shadow: 0 25px 50px rgba(0,0,0,0.7) !important;
        border-radius: 10px !important;
        padding: 0 !important;
      }
      .noc-popup .leaflet-popup-content {
        margin: 0 !important;
      }
      .noc-popup .leaflet-popup-tip {
        background: #1e293b !important;
      }
      .noc-popup .leaflet-popup-close-button {
        color: #94a3b8 !important;
        font-size: 16px !important;
        top: 8px !important;
        right: 8px !important;
      }
      .noc-label {
        background: rgba(15,23,42,0.85) !important;
        border: 1px solid rgba(99,102,241,0.3) !important;
        color: #e2e8f0 !important;
        font-size: 10px !important;
        font-weight: 600 !important;
        border-radius: 4px !important;
        padding: 1px 5px !important;
        white-space: nowrap !important;
        box-shadow: none !important;
      }
      .noc-label::before { display: none !important; }
      .leaflet-container { background: #020817 !important; }
    `;
    document.head.appendChild(style);
  }, []);

  return (
    <div className="space-y-3 pb-16">

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight flex items-center gap-2">
            <MapPin className="w-6 h-6 text-primary" />
            Geographic Network Map
          </h1>
          <p className="text-xs text-muted-foreground">
            Peta topologi jaringan - OpenStreetMap · drag marker ke lokasi fisik
            {stats ? ` · ${devices.length} device` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex rounded-sm border border-border overflow-hidden text-xs">
            {["all","online","offline"].map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`px-3 py-1.5 capitalize transition-colors ${
                  filter === f ? "bg-primary text-primary-foreground" : "hover:bg-secondary/30 text-muted-foreground"
                }`}
              >{f}</button>
            ))}
          </div>
          <button onClick={() => setShowLinks(v => !v)}
            title="Toggle ARP Links"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-sm border text-xs transition ${
              showLinks ? "bg-blue-500/10 border-blue-500/30 text-blue-300" : "border-border text-muted-foreground"
            }`}>
            <Link className="w-3.5 h-3.5" />
            ARP Links
          </button>
          <button onClick={() => setLocked(v => !v)}
            title={locked ? "Aktifkan mode edit drag" : "Kunci posisi marker"}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-sm border text-xs transition ${
              locked ? "bg-slate-700/40 border-slate-600 text-slate-400" : "bg-green-500/10 border-green-500/30 text-green-300"
            }`}>
            {locked ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
            {locked ? "Terkunci" : "Edit Mode"}
          </button>
          <button onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-sm border border-primary/30 bg-primary/10 text-primary text-xs hover:bg-primary/20 transition">
            <Plus className="w-3.5 h-3.5" />
            Tambah
          </button>
          <button onClick={fitAll}
            title="Fit semua marker ke layar"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-sm border border-border text-xs text-muted-foreground hover:bg-secondary/30 transition">
            <LocateFixed className="w-3.5 h-3.5" />
            Fit All
          </button>
          <button onClick={fetchTopology} disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-sm border border-border text-xs text-muted-foreground hover:bg-secondary/30 transition disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      <div className="flex gap-3 flex-wrap">
        {[
          { label: "Total",    value: devices.length, color: "text-foreground" },
          { label: "Online",   value: online,  color: "text-green-400" },
          { label: "Offline",  value: offline, color: "text-red-400" },
          { label: "Warning",  value: warning, color: "text-yellow-400" },
          { label: "ARP Links",value: edges.length, color: "text-blue-400" },
          { label: "Terpetakan",value: devices.filter(d=>d.lat!=null).length, color: "text-purple-400" },
        ].map(s => (
          <div key={s.label} className="bg-card border border-border rounded-sm px-4 py-2 flex flex-col items-center min-w-[80px]">
            <span className={`text-xl font-bold font-mono ${s.color}`}>{s.value}</span>
            <span className="text-[10px] text-muted-foreground uppercase tracking-wide">{s.label}</span>
          </div>
        ))}
      </div>

      {unplaced.length > 0 && (
        <div className="rounded-sm border border-yellow-500/30 bg-yellow-500/5">
          <button
            onClick={() => setShowUnplaced(v => !v)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-xs text-yellow-300"
          >
            <span className="flex items-center gap-2">
              <Info className="w-3.5 h-3.5" />
              <strong>{unplaced.length} device</strong> belum memiliki lokasi di peta — drag marker untuk menempatkan
            </span>
            {showUnplaced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          {showUnplaced && (
            <div className="px-4 pb-3 flex flex-wrap gap-1.5">
              {unplaced.map(d => (
                <span key={d.id} className="text-[10px] bg-yellow-500/10 border border-yellow-500/20 text-yellow-300 rounded px-2 py-0.5 font-mono">
                  {d.identity || d.name}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-4 text-[11px] text-muted-foreground flex-wrap">
        <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded-full bg-green-500 shadow-lg shadow-green-500/40" /><span>Online</span></div>
        <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded-full bg-red-500" /><span>Offline</span></div>
        <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded-full bg-yellow-500" /><span>Warning</span></div>
        <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded-full bg-gray-500" /><span>Unknown</span></div>
        <div className="flex items-center gap-1.5"><div className="border border-dashed border-blue-500 w-6 h-0.5" /><span>ARP Link</span></div>
        {!locked && <span className="text-yellow-300 font-semibold">✏️ Mode Edit - drag marker ke posisi physical</span>}
        {locked  && <span className="text-slate-400">🔒 Posisi terkunci</span>}
      </div>

      <div className="relative rounded-xl overflow-hidden border border-border shadow-xl" style={{ height: "600px" }}>
        <div ref={mapRef} className="w-full h-full" style={{ zIndex: 0 }} />

        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#020817]/60 backdrop-blur-sm z-10 pointer-events-none">
            <div className="flex flex-col items-center gap-2">
              <RefreshCw className="w-8 h-8 text-primary animate-spin" />
              <p className="text-sm text-slate-300">Memuat data peta...</p>
            </div>
          </div>
        )}

        {savingId && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 bg-blue-500/90 text-white text-xs rounded-full px-3 py-1 flex items-center gap-1.5 shadow-lg backdrop-blur">
            <RefreshCw className="w-3 h-3 animate-spin" />
            Menyimpan posisi...
          </div>
        )}

        <button
          onClick={resetView}
          title="Reset ke Jambi"
          className="absolute right-3 bottom-16 z-10 w-8 h-8 bg-[#1e293b]/90 border border-[#334155] text-slate-300 rounded flex items-center justify-center hover:bg-[#334155] transition text-xs font-bold shadow-lg"
        >
          🏠
        </button>
      </div>

      <div className="bg-card border border-border rounded-sm p-3 text-xs text-muted-foreground flex items-start gap-2">
        <Info className="w-4 h-4 text-blue-400 flex-shrink-0 mt-0.5" />
        <div className="space-y-0.5">
          <p>Cara menempatkan device: aktifkan <span className="text-green-300">Edit Mode</span>, lalu drag 📍 marker ke posisi lokasi fisik perangkat di peta. Posisi tersimpan otomatis ke database.</p>
          <p>Scroll untuk zoom · Klik marker untuk detail · ARP Links menampilkan koneksi L2 yang terdeteksi</p>
        </div>
      </div>

      {devices.length > 0 && (
        <div className="bg-card border border-border rounded-sm">
          <div className="px-4 py-3 border-b border-border">
          <p className="text-xs font-semibold">Daftar Device ({devices.length}) - klik untuk lokasi di peta</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border">
                  {["Status","Nama","IP","Lokasi","CPU","Mem","Ping","DL","UL"].map(h => (
                    <th key={h} className="px-3 py-2 text-[10px] text-muted-foreground uppercase tracking-wider font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(filter === "all" ? devices : devices.filter(d => d.status === filter)).map(d => (
                  <tr
                    key={d.id}
                    className="border-b border-border/20 hover:bg-secondary/10 transition-colors cursor-pointer"
                    onClick={() => {
                      const m = markersRef.current[d.id];
                      if (m && leafletRef.current) {
                        leafletRef.current.setView(m.getLatLng(), 14, { animate: true });
                        setTimeout(() => m.openPopup(), 400);
                      }
                    }}
                  >
                    <td className="px-3 py-2">
                      <div className={`w-2 h-2 rounded-full ${
                        d.status==="online" ? "bg-green-500 animate-pulse" :
                        d.status==="offline" ? "bg-red-500" : "bg-gray-500"
                      }`} />
                    </td>
                    <td className="px-3 py-2 text-xs font-semibold">{d.identity || d.name}</td>
                    <td className="px-3 py-2 text-[11px] font-mono text-muted-foreground">{d.ip_address || "-"}</td>
                    <td className="px-3 py-2 text-[11px] text-muted-foreground">
                      {d.lat != null ? (
                        <span className="text-purple-400">📍 {d.location_name || `${d.lat.toFixed(4)}, ${d.lng.toFixed(4)}`}</span>
                      ) : (
                        <span className="text-yellow-600">⚠ belum</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[11px] font-mono">
                      <span className={d.cpu_load>80?"text-red-400":d.cpu_load>60?"text-yellow-400":"text-foreground"}>
                        {d.cpu_load!=null?`${d.cpu_load}%`:"-"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[11px] font-mono">
                      <span className={d.memory_usage>85?"text-red-400":d.memory_usage>70?"text-yellow-400":"text-foreground"}>
                        {d.memory_usage!=null?`${d.memory_usage}%`:"-"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[11px] font-mono text-purple-300">{d.ping_ms!=null?`${d.ping_ms}ms`:"-"}</td>
                    <td className="px-3 py-2 text-[11px] font-mono text-blue-300">{fmtBw(d.download_mbps)}</td>
                    <td className="px-3 py-2 text-[11px] font-mono text-green-300">{fmtBw(d.upload_mbps)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showAddModal && (
        <AddDeviceModal
          defaultCenter={DEFAULT_CENTER}
          onClose={() => setShowAddModal(false)}
          onSaved={() => { setShowAddModal(false); fetchTopology(); }}
        />
      )}
    </div>
  );
}

/* ─── Add Device Modal ─────────────────────────────────────────────────── */
const DEVICE_TYPES = [
  { value: 'ODP',     label: 'ODP — Optical Distribution Point',  color: '#f97316' },
  { value: 'ODC',     label: 'ODC — Optical Distribution Cabinet', color: '#a855f7' },
  { value: 'ONT',     label: 'ONT — Optical Network Terminal',     color: '#06b6d4' },
  { value: 'OLT',     label: 'OLT — Optical Line Terminal',        color: '#ec4899' },
  { value: 'Switch',  label: 'Switch — Network Switch',            color: '#eab308' },
  { value: 'AP',      label: 'AP — Access Point / WiFi',           color: '#3b82f6' },
  { value: 'Router',  label: 'Router — Generic Router',            color: '#22c55e' },
];

function AddDeviceModal({ defaultCenter, onClose, onSaved }) {
  const [form, setForm] = useState({
    device_type: 'ODP',
    name: '',
    ip_address: '',
    description: '',
    lat: defaultCenter[0].toFixed(6),
    lng: defaultCenter[1].toFixed(6),
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) { toast.error('Nama perangkat wajib diisi'); return; }
    setSaving(true);
    try {
      await api.post('/topology/nodes', {
        ...form,
        lat: parseFloat(form.lat) || null,
        lng: parseFloat(form.lng) || null,
      });
      toast.success(`${form.device_type} "${form.name}" berhasil ditambahkan ke peta!`);
      onSaved();
    } catch (e) {
      toast.error('Gagal menyimpan: ' + (e.response?.data?.detail || e.message));
    }
    setSaving(false);
  };

  const selectedType = DEVICE_TYPES.find(t => t.value === form.device_type);

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between p-5 border-b border-border">
          <div className="flex items-center gap-2">
            <Plus className="w-5 h-5 text-primary" />
            <h3 className="font-bold text-base">Tambah Perangkat ke Peta</h3>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-secondary/50 rounded transition">
            <X className="w-4 h-4 text-muted-foreground" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Tipe */}
          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-2">Tipe Perangkat</label>
            <div className="grid grid-cols-2 gap-2">
              {DEVICE_TYPES.map(t => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setForm(f => ({ ...f, device_type: t.value }))}
                  className={`px-3 py-2 rounded-md border text-xs font-semibold text-left transition-all ${
                    form.device_type === t.value
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border text-muted-foreground hover:border-primary/50'
                  }`}
                >
                  <span className="inline-block w-2 h-2 rounded-full mr-1.5" style={{ backgroundColor: t.color }} />
                  {t.value}
                </button>
              ))}
            </div>
            {selectedType && <p className="text-[10px] text-muted-foreground mt-1">{selectedType.label}</p>}
          </div>

          {/* Nama */}
          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1.5">Nama Perangkat *</label>
            <input
              required
              className="w-full border border-border rounded-md px-3 py-2 text-sm bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder={`Contoh: ${form.device_type}-Perumahan-Alam-01`}
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            />
          </div>

          {/* IP */}
          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1.5">IP Address (opsional)</label>
            <input
              className="w-full border border-border rounded-md px-3 py-2 text-sm bg-background text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="192.168.1.x"
              value={form.ip_address}
              onChange={e => setForm(f => ({ ...f, ip_address: e.target.value }))}
            />
          </div>

          {/* Koordinat */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-muted-foreground mb-1.5">Latitude</label>
              <input
                type="number"
                step="any"
                className="w-full border border-border rounded-md px-3 py-2 text-sm bg-background text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-primary"
                value={form.lat}
                onChange={e => setForm(f => ({ ...f, lat: e.target.value }))}
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-muted-foreground mb-1.5">Longitude</label>
              <input
                type="number"
                step="any"
                className="w-full border border-border rounded-md px-3 py-2 text-sm bg-background text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-primary"
                value={form.lng}
                onChange={e => setForm(f => ({ ...f, lng: e.target.value }))}
              />
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground">💡 Isi koordinat sekarang atau kosongkan — Anda bisa drag marker setelah tersimpan.</p>

          {/* Keterangan */}
          <div>
            <label className="block text-xs font-semibold text-muted-foreground mb-1.5">Keterangan (opsional)</label>
            <input
              className="w-full border border-border rounded-md px-3 py-2 text-sm bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="Lokasi gedung, lantai, atau catatan teknis"
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            />
          </div>

          <div className="flex justify-end gap-3 pt-2 border-t border-border">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm rounded-md hover:bg-secondary/50 transition">Batal</button>
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2 bg-primary text-primary-foreground text-sm font-semibold rounded-md hover:bg-primary/90 transition disabled:opacity-50"
            >
              {saving ? 'Menyimpan...' : 'Simpan ke Peta'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
