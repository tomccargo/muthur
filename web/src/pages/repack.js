// Repacking in the browser (docs/PLAYER.md §5, step 2). Mediabunny reads the file from muthur as it is (Range requests)
// and builds a fragmented MP4 for the browser's own player through Media Source Extensions: the picture's packets are
// copied unchanged, the chosen sound track is copied when the browser plays it (AAC, Opus, FLAC), and otherwise
// decoded (AC-3, E-AC-3, DTS) and encoded as stereo FLAC, losslessly. Firefox gets MP4 instead of the MKVs its reader
// stutters on. The browser keeps picture and sound in sync itself.
//
// The build stays about a minute ahead of the playhead and what is well behind is dropped. A seek outside what is
// buffered starts a new build at the key frame before that point; fragmented MP4 keeps the file's own timestamps, so
// the new fragments land where they belong.
import { ALL_FORMATS, AudioSampleSink, AudioSampleSource, EncodedAudioPacketSource, EncodedPacketSink, EncodedVideoPacketSource, Input, Mp4OutputFormat, NullTarget, Output, UrlSource, } from 'mediabunny';
import { registerAc3Decoder } from '@mediabunny/ac3';
import { registerDtsDecoder } from '@mediabunny/dts';
import { registerFlacEncoder } from '@mediabunny/flac-encoder';
const COPY_AUDIO = new Set(['aac', 'opus', 'flac']); // what both browsers play inside an MP4 stream (measured 26 Oct)
const AHEAD = 60; // seconds built ahead of the playhead
const BEHIND = 30; // seconds kept behind it
let registered = false;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const join = (a, b) => { const out = new Uint8Array(a.length + b.length); out.set(a); out.set(b, a.length); return out; };
export class Repack {
    video;
    url;
    opts;
    media = new MediaSource();
    buffer = null;
    queue = [];
    session = 0;
    closed = false;
    trimTo = 0;
    input = null;
    videoTrack = null;
    audioTrack = null;
    copyAudio = false;
    finished = -1; // the session whose build reached the end of the file
    objectUrl = '';
    output = null; // the build running now; cancelled at once when a seek replaces it
    constructor(video, url, opts) {
        this.video = video;
        this.url = url;
        this.opts = opts;
    }
    async start() {
        if (!registered) {
            registerAc3Decoder();
            registerDtsDecoder();
            registerFlacEncoder();
            registered = true;
        }
        this.input = new Input({ source: new UrlSource(this.url, { maxCacheSize: 64 * 2 ** 20 }), formats: ALL_FORMATS });
        this.videoTrack = await this.input.getPrimaryVideoTrack();
        if (!this.videoTrack)
            throw new Error('The file has no picture this browser can read.');
        const audio = await this.input.getAudioTracks();
        this.audioTrack = this.opts.audio != null ? audio[this.opts.audio] ?? audio[0] ?? null : null;
        if (this.audioTrack) {
            this.copyAudio = COPY_AUDIO.has((await this.audioTrack.getCodec()) ?? '');
            if (!this.copyAudio && !(await this.audioTrack.canDecode()))
                this.audioTrack = null; // plays without sound
        }
        this.objectUrl = URL.createObjectURL(this.media);
        this.video.src = this.objectUrl;
        await new Promise((r) => this.media.addEventListener('sourceopen', r, { once: true }));
        const duration = (await this.input.getDurationFromMetadata()) ?? (await this.input.computeDuration());
        if (Number.isFinite(duration) && duration > 0)
            this.media.duration = duration;
        this.video.addEventListener('seeking', this.onSeeking);
        this.video.addEventListener('timeupdate', this.onTime);
        void this.build(0);
    }
    destroy() {
        this.closed = true;
        this.stopBuild();
        this.video.removeEventListener('seeking', this.onSeeking);
        this.video.removeEventListener('timeupdate', this.onTime);
        this.input?.dispose();
        if (this.objectUrl)
            URL.revokeObjectURL(this.objectUrl);
    }
    // -- building ---------------------------------------------------------------------------
    // A build waiting inside the muxer for the other track would never see that it was replaced: cancel its output.
    stopBuild() {
        this.session++;
        void this.output?.cancel().catch(() => undefined);
        this.output = null;
    }
    async build(at) {
        const id = ++this.session;
        const live = () => id === this.session && !this.closed;
        const videoTrack = this.videoTrack;
        const audioTrack = this.audioTrack;
        let output = null;
        try {
            const videoSink = new EncodedPacketSink(videoTrack);
            const key = (await videoSink.getKeyPacket(at, { verifyKeyPackets: true })) ?? (await videoSink.getFirstPacket());
            if (!key || !live())
                return;
            let ftyp = new Uint8Array();
            let moof = new Uint8Array();
            output = new Output({
                format: new Mp4OutputFormat({
                    fastStart: 'fragmented',
                    minimumFragmentDuration: 2,
                    onFtyp: (data) => { ftyp = data.slice(); },
                    onMoov: (data) => this.push(id, join(ftyp, data)),
                    onMoof: (data) => { moof = data.slice(); },
                    onMdat: (data) => this.push(id, join(moof, data)),
                }),
                target: new NullTarget(),
            });
            this.output = output;
            const videoSource = new EncodedVideoPacketSource((await videoTrack.getCodec()));
            output.addVideoTrack(videoSource);
            const audioSource = !audioTrack ? null
                : this.copyAudio ? new EncodedAudioPacketSource((await audioTrack.getCodec()))
                    // Stereo (the browser plays on stereo speakers) in 16-bit: with other depths Chrome rejects the FLAC header (measured).
                    : new AudioSampleSource({ codec: 'flac', transform: { numberOfChannels: 2, sampleFormat: 's16' } });
            if (audioSource)
                output.addAudioTrack(audioSource);
            await output.start();
            if (!this.buffer)
                void output.getMimeType().then((mime) => this.openBuffer(mime)).catch((e) => this.fail(id, e));
            const room = async (t) => { while (live() && t - this.video.currentTime > AHEAD)
                await sleep(250); };
            const pumpVideo = async () => {
                const config = await videoTrack.getDecoderConfig();
                let first = true;
                for await (const packet of videoSink.packets(key)) {
                    await room(packet.timestamp);
                    if (!live())
                        return;
                    await videoSource.add(packet, first && config ? { decoderConfig: config } : undefined);
                    first = false;
                }
                videoSource.close();
            };
            const pumpAudio = async () => {
                if (!audioTrack || !audioSource)
                    return;
                if (audioSource instanceof EncodedAudioPacketSource) {
                    const sink = new EncodedPacketSink(audioTrack);
                    const from = (await sink.getPacket(key.timestamp)) ?? (await sink.getFirstPacket());
                    if (!from)
                        return;
                    const config = await audioTrack.getDecoderConfig();
                    let first = true;
                    for await (const packet of sink.packets(from)) {
                        await room(packet.timestamp);
                        if (!live())
                            return;
                        await audioSource.add(packet, first && config ? { decoderConfig: config } : undefined);
                        first = false;
                    }
                }
                else {
                    for await (const sample of new AudioSampleSink(audioTrack).samples(key.timestamp)) {
                        await room(sample.timestamp);
                        if (!live()) {
                            sample.close();
                            return;
                        }
                        await audioSource.add(sample);
                        sample.close();
                    }
                }
                audioSource.close();
            };
            await Promise.all([pumpVideo(), pumpAudio()]);
            if (!live())
                return;
            await output.finalize();
            this.finished = id;
            this.drain();
        }
        catch (e) {
            this.fail(id, e);
        }
        finally {
            if (output && output.state !== 'finalized' && output.state !== 'canceled')
                void output.cancel().catch(() => undefined);
        }
    }
    fail(id, e) {
        if (id === this.session && !this.closed)
            this.opts.onError(e.message || String(e));
    }
    // -- feeding the browser's player ----------------------------------------------------------
    openBuffer(mime) {
        if (this.buffer || this.closed || this.media.readyState !== 'open')
            return;
        if (!MediaSource.isTypeSupported(mime)) {
            this.opts.onError(`This browser can't play the repacked stream (${mime}).`);
            return;
        }
        this.buffer = this.media.addSourceBuffer(mime);
        this.buffer.mode = 'segments';
        this.buffer.addEventListener('updateend', () => this.drain());
        this.drain();
    }
    push(id, data) {
        if (id !== this.session || this.closed)
            return;
        this.queue.push(data);
        this.drain();
    }
    drain() {
        const b = this.buffer;
        if (!b || b.updating || this.closed)
            return;
        if (this.video.error || this.media.readyState === 'closed') { // the player gave up: stop building, say why once
            this.opts.onError(this.video.error?.message || 'the browser closed the stream');
            this.closed = true;
            this.stopBuild();
            return;
        }
        if (b.buffered.length && b.buffered.start(0) < this.trimTo - 5) {
            b.remove(0, this.trimTo); // what is well behind the playhead goes; updateend drains again
            return;
        }
        const next = this.queue.shift();
        if (next) {
            try {
                b.appendBuffer(next);
            }
            catch (e) {
                if (e.name !== 'QuotaExceededError')
                    throw e;
                this.queue.unshift(next); // full: drop more of what is behind, then try again
                this.trimTo = Math.max(this.trimTo, this.video.currentTime - 10);
                setTimeout(() => this.drain(), 1000);
            }
        }
        else if (this.finished === this.session && this.media.readyState === 'open') {
            this.media.endOfStream();
        }
    }
    onTime = () => {
        this.trimTo = Math.max(0, this.video.currentTime - BEHIND);
    };
    onSeeking = () => {
        const t = this.video.currentTime;
        const b = this.buffer;
        if (b)
            for (let i = 0; i < b.buffered.length; i++)
                if (t >= b.buffered.start(i) && t <= b.buffered.end(i) - 1)
                    return;
        // Outside what is buffered: a new build from the key frame before this point, and the old stream goes.
        this.stopBuild();
        this.queue = [];
        this.trimTo = 0;
        this.finished = -1;
        if (b) {
            if (b.updating)
                b.abort();
            if (b.buffered.length)
                b.remove(0, Infinity);
        }
        void this.build(t);
    };
}
