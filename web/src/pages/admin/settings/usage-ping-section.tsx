// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react";
import { Activity, CheckCircle2, Eye, Loader2, Send, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { admin } from "@/lib/api";
import type { AdminSetting } from "@/lib/types";
import { useSendUsagePing, useUsagePingPreview, useUsagePingStatus } from "@/hooks/use-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

function valueOf(settings: AdminSetting[], key: string, fallback = "") {
  return settings.find((setting) => setting.key === key)?.value ?? fallback;
}

export function UsagePingSection({ settings, onChanged }: { settings: AdminSetting[]; onChanged: () => void }) {
  const { data: status, refetch } = useUsagePingStatus();
  const preview = useUsagePingPreview();
  const sender = useSendUsagePing();
  const [companyName, setCompanyName] = useState(() => valueOf(settings, "usage_ping.company_name"));
  const [enabled, setEnabled] = useState(() => valueOf(settings, "usage_ping.enabled") === "true");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setCompanyName(valueOf(settings, "usage_ping.company_name"));
    setEnabled(valueOf(settings, "usage_ping.enabled") === "true");
  }, [settings]);

  async function save() {
    if (enabled && !companyName.trim()) {
      toast.error("Add the company name before enabling usage reporting");
      return;
    }
    setSaving(true);
    try {
      await admin.updateSetting("usage_ping.company_name", { value: companyName.trim() });
      await admin.updateSetting("usage_ping.enabled", { value: enabled ? "true" : "false" });
      await refetch();
      onChanged();
      toast.success(enabled ? "Weekly usage reporting enabled" : "Usage reporting disabled");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save usage reporting settings");
    } finally {
      setSaving(false);
    }
  }

  async function sendNow() {
    try {
      await sender.mutateAsync();
      toast.success("Usage report accepted by telemetry.observal.io");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not send usage report");
    }
  }

  return (
    <section className="animate-in">
      <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        <Activity className="h-3.5 w-3.5" /> Usage reporting
      </h3>
      <div className="rounded-md border border-border bg-card px-4 py-4 space-y-4">
        <div className="flex items-start justify-between gap-6">
          <div className="max-w-2xl">
            <p className="text-sm font-medium">Share aggregate product usage with Observal</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Sends one report each week to telemetry.observal.io. Reports include company and instance identity,
              version, aggregate counts, feature flags, and harness totals. Prompts, traces, source code, user
              identities, and credentials are never included.
            </p>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Enable weekly usage reporting" />
        </div>

        <div className="grid gap-2 border-t border-border pt-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <label className="space-y-1.5">
            <span className="text-xs font-medium">Company name</span>
            <Input value={companyName} onChange={(event) => setCompanyName(event.target.value)} maxLength={160} placeholder="Acme Engineering" />
          </label>
          <Button onClick={save} disabled={saving}>
            {saving ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <ShieldCheck className="mr-1.5 h-4 w-4" />}
            Save consent
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-border pt-4 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5" /> Destination: {status?.collector_url ?? "telemetry.observal.io"}</span>
          <span>Last sent: {status?.last_success_at ? new Date(status.last_success_at).toLocaleString() : "Never"}</span>
          <span>Next run: {status?.next_scheduled_at ? new Date(status.next_scheduled_at).toLocaleString() : "Loading"}</span>
        </div>
        {status?.last_error ? <p className="text-xs text-destructive">Last delivery failed: {status.last_error}</p> : null}
        {enabled && status && !status.configured ? <p className="text-xs text-warning">Set both the company name and Deployment Public URL before sending.</p> : null}

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => preview.mutate()} disabled={preview.isPending}>
            <Eye className="mr-1.5 h-3.5 w-3.5" /> Preview exact payload
          </Button>
          <Button variant="outline" size="sm" onClick={sendNow} disabled={!status?.enabled || !status.configured || sender.isPending}>
            {sender.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Send className="mr-1.5 h-3.5 w-3.5" />}
            Send now
          </Button>
        </div>

        {preview.data?.payload ? (
          <div className="rounded-md bg-muted/60 p-3">
            <p className="mb-2 text-xs font-medium">Exact payload</p>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-[11px] leading-5 text-muted-foreground">{JSON.stringify(preview.data.payload, null, 2)}</pre>
          </div>
        ) : null}
      </div>
    </section>
  );
}
