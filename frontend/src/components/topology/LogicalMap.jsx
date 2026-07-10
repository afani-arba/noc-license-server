import { useState, useEffect, useRef, useCallback } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import Sigma from "sigma";

import { 
  RefreshCw, Save, LocateFixed, Activity,
  Server, Router, Zap, Search, Settings2
} from "lucide-react";

// Modal untuk aksi ONT Ping
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

// Color palette
const COLORS = {
  online: "#22c55e",
  offline: "#ef4444",
  warning: "#f59e0b",
  unknown: "#6b7280",
  bg: "#020817",
  edgeArp: "#3b82f6",
  edgePppoe: "#a855f7"
};

export default function LogicalMap() {
  const containerRef = useRef(null);
  const sigmaRef = useRef(null);
  const graphRef = useRef(null);
  const forceSupervisorRef = useRef(null);
  
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [layoutRunning, setLayoutRunning] = useState(false);
  const [stats, setStats] = useState(null);
  
  // States for diagnostic ping
  const [selectedNode, setSelectedNode] = useState(null);
  const [pingData, setPingData] = useState(null);
  const [pinging, setPinging] = useState(false);

  const fetchTopology = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/topology");
      const { nodes, edges, stats: st } = res.data;
      setStats(st);
      
      initGraph(nodes, edges);
    } catch (e) {
      toast.error("Gagal memuat logical map");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchTopology();
    return () => cleanupSigma();
  }, [fetchTopology]);

  // Handle Resize
  useEffect(() => {
    const handleResize = () => sigmaRef.current?.refresh();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const cleanupSigma = () => {
    if (forceSupervisorRef.current) {
      clearInterval(forceSupervisorRef.current);
      forceSupervisorRef.current = null;
    }
    if (sigmaRef.current) {
      sigmaRef.current.kill();
      sigmaRef.current = null;
    }
    if (graphRef.current) {
      graphRef.current.clear();
      graphRef.current = null;
    }
  };

  const initGraph = (nodes, edges) => {
    cleanupSigma();
    if (!containerRef.current) return;

    const graph = new Graph({ multi: true });
    
    // Add nodes
    nodes.forEach((n, i) => {
      // Jika topo_x/y belum ada, taruh spiral/random
      const angle = i * 0.3;
      const radius = i * 0.5;
      const x = n.topo_x != null ? parseFloat(n.topo_x) : Math.cos(angle) * radius;
      const y = n.topo_y != null ? parseFloat(n.topo_y) : Math.sin(angle) * radius;
      
      let color = COLORS.unknown;
      if (n.status === "online") color = COLORS.online;
      else if (n.status === "offline") color = COLORS.offline;
      else if (n.status === "warning") color = COLORS.warning;
      // Khusus diag merah kalau ada history ping jelek (nanti)

      const size = n.role === "ont" ? 5 : 18;
      
      graph.addNode(n.id, {
        x, y, size,
        color,
        label: n.label || n.ip || n.id,
        raw: n // Simpan data aslinya
      });
    });

    // Add edges
    edges.forEach(e => {
      if (graph.hasNode(e.source) && graph.hasNode(e.target)) {
        graph.addEdge(e.source, e.target, {
          size: e.type === "pppoe" ? 1.5 : 3,
          color: e.type === "pppoe" ? COLORS.edgePppoe : COLORS.edgeArp,
          type: e.dashed ? "dashed" : "line"
        });
      }
    });

    graphRef.current = graph;

    // Load Sigma
    const sigma = new Sigma(graph, containerRef.current, {
      renderLabels: true,
      labelFont: "Inter",
      labelWeight: "600",
      labelColor: { color: "#e2e8f0" },
      labelGridCellSize: 100,
      labelDensity: 2,
      // Default node renderer + glowing
      defaultNodeColor: COLORS.online,
      defaultEdgeType: "line"
    });
    
    sigmaRef.current = sigma;

    // Setup State for Dragging
    let isDragging = false;
    let draggedNode = null;

    sigma.on("downNode", (e) => {
      isDragging = true;
      draggedNode = e.node;
      sigma.getCustomBBox = () => sigma.getBBox();
      graph.setNodeAttribute(e.node, "highlighted", true);
    });

    sigma.getMouseCaptor().on("mousemovebody", (e) => {
      if (!isDragging || !draggedNode) return;
      const pos = sigma.viewportToGraph(e);
      graph.setNodeAttribute(draggedNode, "x", pos.x);
      graph.setNodeAttribute(draggedNode, "y", pos.y);
      e.preventSigmaDefault();
      e.original.preventDefault();
      e.original.stopPropagation();
    });

    const handleUp = () => {
      if (draggedNode) {
        graph.setNodeAttribute(draggedNode, "highlighted", false);
        // Automatically save on drop
        saveNodeDebounced();
      }
      isDragging = false;
      draggedNode = null;
      sigma.getCustomBBox = () => sigma.getBBox();
    };

    sigma.getMouseCaptor().on("mouseup", handleUp);
    sigma.getMouseCaptor().on("mousemove", (e) => {
      if (isDragging) {
        // Prevent pan when dragging node
        e.preventSigmaDefault();
      }
    });

    // Click node untuk tools
    sigma.on("clickNode", (e) => {
      const attrs = graph.getNodeAttributes(e.node);
      if (attrs.raw && attrs.raw.role === "ont") {
        setSelectedNode(attrs.raw);
        setPingData(null);
      } else {
        toast.info("Device: " + attrs.raw.label + " | IP: " + attrs.raw.ip);
      }
    });

    // Jika grafnya berantakan banget (node semua 0,0), jalankan layout sekali sekilas
    const needsLayout = nodes.some(n => n.topo_x == null) && nodes.length > 1;
    if (needsLayout) {
      toggleLayout(true, graph);
      setTimeout(() => toggleLayout(false, graph), 2000); // Settle 2s
    } else {
      setTimeout(() => sigma.refresh(), 200);
    }
  };

  const toggleLayout = (forceStart = false, gRef = graphRef.current) => {
    if (!gRef) return;
    if (layoutRunning && !forceStart) {
      if (forceSupervisorRef.current) clearInterval(forceSupervisorRef.current);
      forceSupervisorRef.current = null;
      setLayoutRunning(false);
      saveNodeDebounced();
    } else {
      if (!forceSupervisorRef.current) {
         // Use interval to simulate worker ticking and avoid freezing UI for large graphs
        forceSupervisorRef.current = setInterval(() => {
          forceAtlas2.assign(gRef, {
            settings: {
              barnesHutOptimize: true,
              strongGravityMode: true,
              gravity: 0.1,
              scalingRatio: 80,
              slowDown: 10
            },
            iterations: 20
          });
        }, 50);
      }
      setLayoutRunning(true);
    }
  };

  let saveTimeout;
  const saveNodeDebounced = () => {
    clearTimeout(saveTimeout);
    saveTimeout = setTimeout(saveAllPositions, 2000);
  };

  const saveAllPositions = async () => {
    if (!graphRef.current) return;
    setSaving(true);
    try {
      const nodes = graphRef.current.nodes();
      const updates = [];
      nodes.forEach(nId => {
        const attrs = graphRef.current.getNodeAttributes(nId);
        // Jangan simpan ONT positions, buang waktu db call saja
        if (attrs.raw && attrs.raw.role !== "ont") {
          updates.push(
            api.patch(`/devices/${nId}/topo-location`, { x: attrs.x, y: attrs.y }).catch(()=>null)
          );
        }
      });
      await Promise.all(updates);
      toast.success("Posisi Logical Topology tersimpan!");
    } catch (e) {
      toast.error("Gagal menyimpan koordinat lokal");
    }
    setSaving(false);
  };

  const fitView = () => {
    sigmaRef.current?.getCamera().animatedReset({ duration: 600 });
  };

  const runPingTest = async (ont) => {
    setPinging(true);
    try {
      const res = await api.post("/topology/ping-ont", {
        router_id: ont.parent_router_id,
        target_ip: ont.ip
      });
      setPingData(res.data);
      
      // Ganti warna node ONT seketika di canvas!
      if (graphRef.current && graphRef.current.hasNode(ont.id)) {
        let color = COLORS.online;
        if (res.data.status === "timeout") color = COLORS.offline;
        else if (res.data.status === "warning") color = COLORS.warning;
        
        graphRef.current.setNodeAttribute(ont.id, "color", color);
        sigmaRef.current?.refresh();
      }
      
    } catch (e) {
      toast.error(e.response?.data?.detail || "Gagal ping!");
    }
    setPinging(false);
  };

  return (
    <div className="space-y-4">
      {/* Toolbox Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Network className="w-5 h-5 text-indigo-400" /> Logical Network Topology
          </h1>
          <p className="text-xs text-muted-foreground">Interactive Force-Directed Graph Â· Drag Nodes Â· Auto-Save</p>
        </div>
        
        <div className="flex gap-2">
          {stats?.ont_count > 0 && (
            <div className="px-3 py-1.5 bg-purple-500/10 border border-purple-500/20 text-purple-300 rounded-sm text-xs flex items-center font-semibold">
              <Zap className="w-3.5 h-3.5 mr-1" /> {stats.ont_count} PPPoE ONTs
            </div>
          )}
          
          <Button variant="outline" size="sm" onClick={() => toggleLayout()} className={`h-8 gap-1.5 rounded-sm ${layoutRunning?"border-amber-500 text-amber-500":"border-border"}`}>
            <Activity className="w-3.5 h-3.5" /> {layoutRunning ? "Stop Gravity" : "Reset Layout"}
          </Button>
          <Button variant="outline" size="sm" onClick={fitView} className="h-8 gap-1.5 rounded-sm">
            <LocateFixed className="w-3.5 h-3.5" /> Fit View
          </Button>
          <Button variant="outline" size="sm" onClick={fetchTopology} disabled={loading} className="h-8 gap-1.5 rounded-sm">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </Button>
          <Button variant="default" size="sm" onClick={saveAllPositions} disabled={saving} className="h-8 gap-1.5 rounded-sm">
            <Save className={`w-3.5 h-3.5 ${saving ? "animate-spin" : ""}`} /> Save Map
          </Button>
        </div>
      </div>

      {/* Main Graph Area */}
      <div className="relative border border-border shadow-2xl rounded-sm overflow-hidden" style={{ height: "65vh" }}>
        
        {/* The DOM Element for WebGL Canvas */}
        <div ref={containerRef} className="w-full h-full bg-[#030712] outline-none" />

        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/50 backdrop-blur-sm pointer-events-none">
            <RefreshCw className="w-8 h-8 animate-spin text-indigo-500" />
          </div>
        )}
        
        {/* Floating Legend */}
        <div className="absolute bottom-4 left-4 z-10 bg-[#0f172a]/90 backdrop-blur border border-slate-700 p-3 rounded-md shadow-lg pointer-events-none">
          <p className="text-[10px] font-bold uppercase text-slate-400 mb-2 font-mono">MAP LEGEND</p>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px] text-slate-300">
            <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-[#22c55e]" /> Online</div>
            <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-[#ef4444]" /> Offline</div>
            <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-[#f59e0b]" /> Warning</div>
            <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-[#6b7280]" /> Unknown</div>
            <div className="flex items-center gap-2 mt-1 col-span-2 border-t border-slate-700 pt-2">
              <div className="w-4 h-[3px] bg-[#3b82f6]" /> ARP Connection
            </div>
            <div className="flex items-center gap-2 col-span-2">
              <div className="w-4 h-[2px] bg-[#a855f7]" /> PPPoE Client (ONT)
            </div>
          </div>
        </div>

      </div>

      {/* ONT Diagnostic Modal */}
      <Dialog open={!!selectedNode} onOpenChange={(v) => !v && setSelectedNode(null)}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-indigo-500" /> ONT Diagnostic
            </DialogTitle>
            <DialogDescription>
              Test konektivitas FO ke {selectedNode?.label || "Unknown"}
            </DialogDescription>
          </DialogHeader>
          
          <div className="py-2 space-y-4">
             <div className="grid grid-cols-2 gap-4 bg-muted/30 p-3 rounded-md border text-sm">
                <div>
                  <p className="text-xs text-muted-foreground uppercase">Username PPPoE</p>
                  <p className="font-semibold">{selectedNode?.label}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground uppercase">IP Client</p>
                  <p className="font-mono">{selectedNode?.ip}</p>
                </div>
                <div className="col-span-2">
                  <p className="text-xs text-muted-foreground uppercase">Uptime Server</p>
                  <p className="font-mono text-emerald-400">{selectedNode?.uptime}</p>
                </div>
             </div>

             {pingData && (
                <div className={`p-4 rounded-md border ${
                  pingData.status === "healthy" ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" :
                  pingData.status === "warning" ? "bg-amber-500/10 border-amber-500/30 text-amber-500" :
                  "bg-red-500/10 border-red-500/30 text-red-400"
                }`}>
                  <h4 className="font-bold flex items-center justify-between">
                    Result: {pingData.message}
                    {pingData.status === "healthy" && <span className="text-xl">ðŸ‘ </span>}
                    {pingData.status === "warning" && <span className="text-xl">⚠️ï¸ </span>}
                    {pingData.status === "timeout" && <span className="text-xl">â Œ</span>}
                  </h4>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-center text-sm font-mono">
                    <div className="bg-background/40 p-2 rounded">
                      <p className="text-xs opacity-70 mb-1">Avg Latency</p>
                      <p className="text-lg">{pingData.latency_ms} <span className="text-xs">ms</span></p>
                    </div>
                    <div className="bg-background/40 p-2 rounded">
                      <p className="text-xs opacity-70 mb-1">Packet Loss</p>
                      <p className="text-lg">{pingData.loss} <span className="text-xs">%</span></p>
                    </div>
                  </div>
                </div>
             )}
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelectedNode(null)}>Close</Button>
            <Button onClick={() => runPingTest(selectedNode)} disabled={pinging} className="gap-2">
              <Zap className={`w-4 h-4 ${pinging?'animate-pulse':''}`} /> 
              {pinging ? "Pinging..." : "Run Ping Test"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
