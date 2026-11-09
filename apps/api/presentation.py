"""Project worker evidence into typed, owned browser views without judging science."""
import json

from packages.contracts.presentation import (
    ArtifactView, AttemptView, ContainmentView, ExperimentView, JobView, ProvenanceView, ReportView,
)

ROLES = {'primary': 'Primary', 'refinement': 'Refinement', 'held_out': 'Held-out', 'verification': 'Verifier'}


def experiment_view(store, row):
    published = store.artifacts(row['id'], row['session_id'])
    files = {item['name']: item for item in published}
    labels = {}

    def artifact(item, label=None):
        return ArtifactView(id=item['id'], name=item['name'], label=label or item['name'],
                            size=item['size'], sha256=item['sha256'])

    report = None
    if row['report']:
        raw = json.loads(row['report'])
        diagnostic = raw.get('following_healthy', raw) if row['kind'] == 'containment' else raw
        attempts = []
        for attempt in diagnostic.get('attempts', []):
            revision = attempt['revision']
            source_name = f'revision-{revision}.py'
            labels[source_name] = 'Original simulation' if revision == 0 else f'Candidate {revision} simulation'
            jobs = []
            for job in attempt['jobs']:
                role = job['role']
                available = []
                for original in job['artifacts']:
                    name = f'{job["job_id"]}-{original["id"]}'
                    if name in files:
                        item = files[name]
                        if item['sha256'] != original['sha256'] or item['size'] != original['size']:
                            raise ValueError('published artifact binding mismatch')
                        label = f'{"Original" if revision == 0 else "Candidate " + str(revision)} · {ROLES[role]} · {original["name"]}'
                        labels[name] = label
                        available.append(artifact(item, label))
                jobs.append(JobView(job_id=job['job_id'], role=role, execution=job['execution'], artifacts=available))
            attempts.append(AttemptView(revision=revision, parameters=attempt['parameters'], source=attempt['source'],
                                        jobs=jobs, verification=attempt.get('verification')))
        provenance = diagnostic.get('provenance', {})
        images = provenance.get('images') or {}
        containment = None
        if row['kind'] == 'containment' and 'observations' in raw:
            containment = ContainmentView(connections=raw['observations']['connections'],
                positive_control=raw['host_listener_positive_control'], messages_received=raw['probe_messages_received'],
                cleanup=raw['probe']['execution']['cleanup'], runner_healthy_after=raw['runner_healthy_after'])
        report = ReportView(outcome=raw['outcome'], evidence_expired=raw.get('evidence_expired', False),
            error=raw.get('error'), hypothesis=diagnostic.get('hypothesis'), patch=diagnostic.get('patch', ''),
            attempts=attempts, limitations=raw.get('limitations', diagnostic.get('limitations', [])), containment=containment,
            provenance=ProvenanceView(model_id=diagnostic.get('model_id'), mode=diagnostic.get('mode'),
                model_calls=diagnostic.get('model_calls'), jobs_used=diagnostic.get('jobs_used'),
                model_usage=diagnostic.get('model_usage', []), git_sha=provenance.get('git_sha'),
                working_tree_dirty=provenance.get('working_tree_dirty'), simulation_image=images.get('simulation_image'),
                verifier_image=images.get('verifier_image'), spec_hash=provenance.get('spec_hash'),
                verifier_hash=provenance.get('verifier_hash'), runtime_policy=provenance.get('runtime_policy'),
                elapsed_seconds=diagnostic.get('elapsed_seconds')))
    labels['report.json'] = 'Complete evidence report (JSON)'
    return ExperimentView(experiment_id=row['id'], fixture_id=row['fixture'], kind=row['kind'],
        status=row['status'], created_at=row['created'], ended_at=row['ended'], cancel_requested=bool(row['cancel']),
        report=report, artifacts=[artifact(item, labels.get(item['name'])) for item in published])
