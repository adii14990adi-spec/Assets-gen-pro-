import React from "react";
import { CheckCircle2, Cpu, RefreshCw, X, AlertCircle } from "lucide-react";
import type { CapabilityStatus } from "../types/studio";

interface CapabilitiesModalProps {
  open: boolean;
  capabilities: CapabilityStatus[];
  isRefreshing: boolean;
  onRefresh: () => void;
  onClose: () => void;
}

export const CapabilitiesModal: React.FC<CapabilitiesModalProps> = ({
  open,
  capabilities,
  isRefreshing,
  onRefresh,
  onClose,
}) => {
  if (!open) return null;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Capability Registry">
      <div className="modal-panel">
        <div className="modal-header">
          <div className="modal-title-row">
            <Cpu size={19} className="accent-icon" />
            <div>
              <h2>Blender &amp; Python Capability Registry</h2>
              <p>Live runtime verification of modeling extensions, versions, licenses, and fallback adapters.</p>
            </div>
          </div>
          <div className="modal-actions">
            <button type="button" className="vp-btn" onClick={onRefresh} disabled={isRefreshing}>
              <RefreshCw size={14} className={isRefreshing ? "spin" : ""} />
              <span>Re-verify</span>
            </button>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="cap-grid">
          {capabilities.map((cap) => (
            <div key={cap.id} className={`cap-card ${cap.verified ? "verified" : "fallback"}`}>
              <div className="cap-head">
                <div className="cap-status-icon">
                  {cap.verified ? (
                    <CheckCircle2 size={17} className="ic-pass" />
                  ) : (
                    <AlertCircle size={17} className="ic-warn" />
                  )}
                  <strong>{cap.name}</strong>
                </div>
                <span className="cap-ver">{cap.version ? `v${cap.version}` : "Fallback Mode"}</span>
              </div>
              <p className="cap-msg">{cap.status_message}</p>
              <div className="cap-meta">
                <span>Kind: {cap.kind.replace("_", " ")}</span>
                <span>License: {cap.license}</span>
                <span>Applies to: {cap.applicable_categories.join(", ")}</span>
              </div>
              <div className="cap-fallback">
                Fallback adapter: <code>{cap.fallback_strategy}</code>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
