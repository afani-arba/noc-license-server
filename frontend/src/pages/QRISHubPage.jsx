import React, { useState, useEffect } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { RefreshCw, QrCode, Search, CheckCircle2, XCircle, Clock, Eye } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

const Rp = (n) => `Rp ${(Number(n) || 0).toLocaleString("id-ID")}`;

export default function QRISHubPage() {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [checkingId, setCheckingId] = useState(null);
  const [selectedQR, setSelectedQR] = useState(null);

  const fetchTransactions = async () => {
    try {
      setLoading(true);
      const res = await api.get("/qris/admin/transactions");
      setTransactions(res.data.transactions || []);
    } catch (err) {
      toast.error("Gagal mengambil data transaksi QRIS.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTransactions();
  }, []);

  const handleCheckStatus = async (txId) => {
    try {
      setCheckingId(txId);
      const res = await api.post(`/qris/admin/transactions/${txId}/check`);
      if (res.data.message.includes("PAID")) {
          toast.success(res.data.message);
          fetchTransactions(); // Refresh
      } else {
          toast.info(res.data.message);
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal mengecek status ke BRI");
    } finally {
      setCheckingId(null);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-10">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <QrCode className="w-6 h-6 text-primary" />
            QRIS HUB
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Monitoring sentral seluruh transaksi QRIS yang digenerate oleh klien
          </p>
        </div>
        <Button onClick={fetchTransactions} variant="outline" disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <div className="bg-card border border-border rounded-md shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-muted-foreground bg-muted/50 uppercase font-semibold border-b border-border">
              <tr>
                <th className="px-4 py-3 whitespace-nowrap">Waktu</th>
                <th className="px-4 py-3 whitespace-nowrap">Klien (Tenant)</th>
                <th className="px-4 py-3 whitespace-nowrap">Pelanggan</th>
                <th className="px-4 py-3 whitespace-nowrap">Invoice</th>
                <th className="px-4 py-3 whitespace-nowrap">Ref / Trx ID</th>
                <th className="px-4 py-3 whitespace-nowrap text-right">Nominal</th>
                <th className="px-4 py-3 whitespace-nowrap text-center">Status</th>
                <th className="px-4 py-3 whitespace-nowrap text-center">Aksi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading && transactions.length === 0 ? (
                <tr>
                  <td colSpan="8" className="px-4 py-8 text-center text-muted-foreground">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-primary" />
                    Memuat data...
                  </td>
                </tr>
              ) : transactions.length === 0 ? (
                <tr>
                  <td colSpan="8" className="px-4 py-8 text-center text-muted-foreground">
                    Belum ada transaksi QRIS.
                  </td>
                </tr>
              ) : (
                transactions.map((tx) => (
                  <tr key={tx.id} className="hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-3 whitespace-nowrap text-xs font-mono">
                      {new Date(tx.created_at).toLocaleString('id-ID', {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'})}
                    </td>
                    <td className="px-4 py-3">
                        <div className="font-semibold text-foreground">{tx.client_name}</div>
                        <div className="text-xs text-muted-foreground font-mono">{tx.client_id}</div>
                    </td>
                    <td className="px-4 py-3 font-medium text-foreground">{tx.customer_name || "-"}</td>
                    <td className="px-4 py-3 text-xs font-mono">{tx.noc_invoice_number || "-"}</td>
                    <td className="px-4 py-3 text-xs font-mono">
                        <div className="text-primary truncate max-w-[150px]" title={tx.partner_reference_no}>
                            {tx.partner_reference_no}
                        </div>
                    </td>
                    <td className="px-4 py-3 text-right font-semibold font-mono text-primary">
                      {Rp(tx.amount)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {tx.status === "paid" ? (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-semibold bg-emerald-100 text-emerald-700 border border-emerald-200">
                          <CheckCircle2 className="w-3 h-3" /> PAID
                        </span>
                      ) : tx.status === "failed" ? (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-semibold bg-rose-100 text-rose-700 border border-rose-200">
                          <XCircle className="w-3 h-3" /> FAILED
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-700 border border-amber-200">
                          <Clock className="w-3 h-3" /> PENDING
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex items-center justify-center gap-2">
                        {tx.status === "pending" && (
                            <Button
                                size="sm"
                                variant="outline"
                                className="h-7 text-xs px-2"
                                onClick={() => handleCheckStatus(tx.id)}
                                disabled={checkingId === tx.id}
                            >
                                {checkingId === tx.id ? (
                                    <RefreshCw className="w-3 h-3 animate-spin mr-1" />
                                ) : (
                                    <Search className="w-3 h-3 mr-1" />
                                )}
                                Check
                            </Button>
                        )}
                        {tx.qr_url && (
                             <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 w-7 p-0"
                                onClick={() => setSelectedQR(tx)}
                                title="Lihat QR Code"
                             >
                                <Eye className="w-4 h-4 text-muted-foreground" />
                             </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      
      {/* QR Code Viewer Dialog */}
      <Dialog open={!!selectedQR} onOpenChange={() => setSelectedQR(null)}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>QRIS Tagihan</DialogTitle>
          </DialogHeader>
          {selectedQR && (
              <div className="flex flex-col items-center justify-center p-4">
                  <h3 className="font-bold text-lg mb-1">{selectedQR.customer_name}</h3>
                  <p className="text-muted-foreground text-sm mb-4">Invoice: {selectedQR.noc_invoice_number}</p>
                  
                  <div className="bg-white p-4 rounded-lg shadow-sm border border-gray-100 mb-4">
                      <img src={selectedQR.qr_url} alt="QRIS Code" className="w-48 h-48 object-contain" />
                  </div>
                  
                  <div className="text-2xl font-bold text-primary font-mono bg-primary/10 px-4 py-2 rounded-md">
                      {Rp(selectedQR.amount)}
                  </div>
                  
                  <p className="text-xs text-muted-foreground mt-6 text-center font-mono">
                      Ref: {selectedQR.partner_reference_no}
                  </p>
              </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
