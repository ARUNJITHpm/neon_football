"""Boot-scoped source tracking and marker mappings; receipt never implies exposure time."""
from collections import Counter
from core.sensors import SensorAlignment, SensorPacket, SensorSample, SensorSettings
from .protocol import FLAG_NAMES


class SensorHost:
    def __init__(self, settings: SensorSettings, bindings, alignments=(), host_clock_domain="host", evidence="unverified"):
        self.settings = SensorSettings.model_validate(settings.model_dump())
        self.bindings = dict(bindings)
        if evidence not in ("synthetic", "venue", "unverified") or not 1 <= len(bindings) <= 16:
            raise ValueError("Register bounded sensor bindings and evidence provenance")
        self.alignments = {}
        for a in alignments:
            a = SensorAlignment.model_validate(a.model_dump())
            if (a.device_id, a.boot_id) in self.alignments or a.device_id not in bindings or a.host_clock_domain != host_clock_domain:
                raise ValueError("Duplicate/unregistered alignment or clock domain")
            if evidence == "venue" and a.evidence != "physical":
                raise ValueError("Synthetic timing cannot qualify venue data")
            self.alignments[a.device_id, a.boot_id] = a
        self.host_clock_domain, self.evidence = host_clock_domain, evidence
        self.streams, self.boots, self.retired = {}, {}, {}
        self.transport_epochs = {}
        self.quarantined_boots = set()
        self.counters = Counter()

    def process(self, packet, received_seconds, transport_epoch=0):
        packet = SensorPacket.model_validate(packet.model_dump())
        if not isinstance(received_seconds, (int, float)) or not 0 <= received_seconds < float("inf"):
            raise ValueError("Invalid host receipt")
        device = packet.device_id
        if self.bindings.get(device) != packet.goal_end:
            raise ValueError("Unknown device or wrong configured goal end")
        if (device, packet.boot_id) in self.quarantined_boots:
            self.counters["quarantined_packets"] += 1
            return []
        old_epoch = self.transport_epochs.get(device, transport_epoch)
        if transport_epoch < old_epoch:
            self.counters["retired_transport_packets"] += 1
            return []
        if transport_epoch > old_epoch:
            self.streams = {key: value for key, value in self.streams.items() if key[0] != device}
            self.counters["transport_resets"] += 1
        self.transport_epochs[device] = transport_epoch
        flags = [name for bit, name in FLAG_NAMES.items() if packet.flags & bit]
        for flag in flags:
            self.counters["flag_"+flag] += 1
        retired = self.retired.setdefault(device, set())
        if packet.boot_id in retired:
            self.counters["retired_boot_packets"] += 1
            return []
        old_boot = self.boots.get(device)
        if old_boot is not None and old_boot != packet.boot_id:
            if len(retired) >= 64:
                raise ValueError("Too many reboots; partition the acquisition session")
            retired.add(old_boot)
            self.streams = {key: value for key, value in self.streams.items() if key[0] != device}
            self.counters["reboots"] += 1
            flags.append("boot_reset")
        self.boots[device] = packet.boot_id
        key = (device, packet.role)
        state = self.streams.setdefault(key, dict(packet_sequence=None, next_sample=None, last_device=None,
            last_receipt=None, last_fresh_receipt=None, flags=[]))
        if state["last_receipt"] is not None and received_seconds < state["last_receipt"]:
            raise ValueError("Host receipt regressed")
        if state["packet_sequence"] is not None:
            if packet.packet_sequence <= state["packet_sequence"]:
                self.counters["duplicate_or_reordered_packets"] += 1
                return []
            missing = packet.packet_sequence-state["packet_sequence"]-1
            if missing:
                self.counters["missing_packets"] += missing
                flags.append("packet_gap")
        first = packet.first_device_us/1e6
        if packet.samples and state["last_device"] is not None and first <= state["last_device"]:
            self.counters["clock_or_sample_regressions"] += 1
            state["flags"] = ["clock_reset_requires_new_boot"]
            self.quarantined_boots.add((device, packet.boot_id))
            return []
        if packet.samples and state["next_sample"] is not None:
            gap = packet.first_sample_sequence-state["next_sample"]
            if gap < 0:
                self.counters["overlapping_samples"] += 1
                return []
            if gap:
                self.counters["missing_samples"] += gap
                flags.append("sample_gap")
            elif abs(first-(state["last_device"]+.00125)) > .0002:
                flags.append("sample_time_gap")
                self.counters["sample_time_gaps"] += 1
        state["packet_sequence"], state["last_receipt"] = packet.packet_sequence, received_seconds
        state["flags"] = list(flags)
        samples = []
        alignment = self.alignments.get((device, packet.boot_id))
        for index, raw in enumerate(packet.samples):
            source = first+index/800
            local = list(flags)
            aligned = uncertainty = None
            if alignment and alignment.valid_from_device_seconds <= source <= alignment.valid_to_device_seconds:
                aligned = alignment.host_origin_seconds+alignment.scale*(source-alignment.source_origin_seconds)
                uncertainty = alignment.uncertainty_seconds+alignment.scale*packet.timestamp_uncertainty_us/1e6
                if aligned < 0 or aligned > received_seconds+uncertainty:
                    local.append("mapping_in_future")
                    aligned = uncertainty = None
                elif received_seconds-aligned > self.settings.max_delivery_age_seconds:
                    local.append("stale_delivery")
            else:
                local.append("alignment_unavailable_or_expired")
            if uncertainty is not None and uncertainty > self.settings.max_timing_uncertainty_seconds:
                local.append("timing_uncertainty_exceeds_budget")
            if any(abs(v) >= 3900 for v in raw):
                local.append("saturated")
                self.counters["saturated_samples"] += 1
            samples.append(SensorSample(goal_end=packet.goal_end, role=packet.role, device_id=device, boot_id=packet.boot_id,
                sequence=packet.first_sample_sequence+index, device_seconds=source, received_seconds=received_seconds,
                transport_epoch=transport_epoch,
                aligned_seconds=aligned, timing_uncertainty_seconds=uncertainty, host_clock_domain=self.host_clock_domain,
                evidence=self.evidence, xyz_g=tuple(v*self.settings.scale_g_per_lsb for v in raw), flags=sorted(set(local))))
        if samples:
            state["last_sample_flags"] = samples[-1].flags
            state["next_sample"] = packet.first_sample_sequence+len(samples)
            state["last_device"] = samples[-1].device_seconds
            if not any(f in samples[-1].flags for f in ("sensor_missing", "stale_delivery", "mapping_in_future")):
                state["last_fresh_receipt"] = received_seconds
        self.counters["accepted_packets"] += 1
        self.counters["accepted_samples"] += len(samples)
        return samples

    def health(self, now):
        result = []
        for device, end in sorted(self.bindings.items()):
            for role in ("net", "frame"):
                state = self.streams.get((device, role))
                fresh = state["last_fresh_receipt"] if state else None
                flags = sorted(set(state["flags"]+state.get("last_sample_flags", []))) if state else ["not_seen"]
                result.append(dict(device_id=device, goal_end=end, role=role,
                    state="stale" if fresh is None or now-fresh > self.settings.stale_seconds else
                        "degraded" if set(flags)-{"timestamp_estimated", "boot_reset"} else "receiving",
                    last_sample_receipt=fresh, flags=flags,
                    alignment_registered=(device, self.boots.get(device)) in self.alignments))
        return result
