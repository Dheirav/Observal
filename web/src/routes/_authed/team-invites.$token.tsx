// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Building2, CheckCircle2, Loader2, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layouts/page-header";
import { ErrorState } from "@/components/shared/error-state";
import { useRequestJoin, useTeamInvitePreview } from "@/hooks/use-api";

function TeamInvitePage() {
	const { token } = Route.useParams();
	const preview = useTeamInvitePreview(token);
	const requestJoin = useRequestJoin(preview.data?.team_id ?? undefined);
	const [requested, setRequested] = useState(false);

	return (
		<>
			<PageHeader title="Private teamspace invitation" breadcrumbs={[{ label: "Registry", href: "/" }]} />
			<main className="flex min-h-[60vh] items-center justify-center p-6">
				{preview.isLoading ? (
					<Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
				) : preview.isError ? (
					<ErrorState message={preview.error?.message} onRetry={() => preview.refetch()} />
				) : !preview.data?.valid || !preview.data.team_id ? (
					<div className="max-w-md rounded-lg border bg-card p-8 text-center">
						<Lock className="mx-auto h-10 w-10 text-muted-foreground" />
						<h1 className="mt-4 text-xl font-semibold">Invite unavailable</h1>
						<p className="mt-2 text-sm text-muted-foreground">This link is invalid, expired, exhausted, or revoked.</p>
						<Button asChild className="mt-6"><Link to="/">Back to registry</Link></Button>
					</div>
				) : (
					<div className="w-full max-w-lg rounded-lg border bg-card p-8 text-center shadow-sm">
						{requested ? <CheckCircle2 className="mx-auto h-10 w-10 text-success" /> : <Building2 className="mx-auto h-10 w-10 text-primary-accent" />}
						<h1 className="mt-4 text-2xl font-semibold">{preview.data.team_name}</h1>
						<p className="mt-1 font-mono text-xs text-muted-foreground">{preview.data.team_handle}</p>
						{preview.data.team_description && <p className="mt-4 text-sm text-muted-foreground">{preview.data.team_description}</p>}
						{preview.data.invited_by && <p className="mt-3 text-xs text-muted-foreground">Invited by {preview.data.invited_by}</p>}
						{requested ? (
							<p className="mt-6 text-sm text-success">Access requested. A teamspace owner must approve you before membership is granted.</p>
						) : (
							<Button
								className="mt-6"
								disabled={requestJoin.isPending}
								onClick={() => requestJoin.mutate({ invite_token: token }, { onSuccess: () => setRequested(true) })}
							>
								{requestJoin.isPending && <Loader2 className="animate-spin" />} Request access
							</Button>
						)}
					</div>
				)}
			</main>
		</>
	);
}

export const Route = createFileRoute("/_authed/team-invites/$token")({
	component: TeamInvitePage,
});
