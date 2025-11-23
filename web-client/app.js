/**
 * Real-Time Transcription Client
 * Handles WebRTC audio capture and WebSocket streaming
 */

class TranscriptionClient {
    constructor() {
        this.ws = null;
        this.mediaRecorder = null;
        this.audioStream = null;
        this.sessionId = null;
        this.startTime = null;
        this.wordCount = 0;
        this.durationInterval = null;

        // Configuration
        this.config = {
            gatewayUrl: 'ws://localhost:8000/v1/stream',
            apiKey: '',
            language: 'en',
            model: 'large-v3',
            enableDiarization: true
        };

        this.initializeUI();
    }

    initializeUI() {
        // Get elements
        this.elements = {
            startBtn: document.getElementById('startBtn'),
            stopBtn: document.getElementById('stopBtn'),
            status: document.getElementById('status'),
            transcript: document.getElementById('transcript'),
            apiKey: document.getElementById('apiKey'),
            language: document.getElementById('language'),
            model: document.getElementById('model'),
            diarization: document.getElementById('diarization'),
            wordCount: document.getElementById('wordCount'),
            duration: document.getElementById('duration'),
            latency: document.getElementById('latency')
        };

        // Event listeners
        this.elements.startBtn.addEventListener('click', () => this.start());
        this.elements.stopBtn.addEventListener('click', () => this.stop());

        // Config change listeners
        this.elements.apiKey.addEventListener('change', (e) => {
            this.config.apiKey = e.target.value;
        });
        this.elements.language.addEventListener('change', (e) => {
            this.config.language = e.target.value;
        });
        this.elements.model.addEventListener('change', (e) => {
            this.config.model = e.target.value;
        });
        this.elements.diarization.addEventListener('change', (e) => {
            this.config.enableDiarization = e.target.checked;
        });
    }

    updateStatus(status, className) {
        this.elements.status.textContent = status;
        this.elements.status.className = `status-${className}`;
    }

    async start() {
        if (!this.config.apiKey) {
            alert('Please enter an API key');
            return;
        }

        try {
            // Request microphone access
            this.audioStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: 16000,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            });

            // Connect WebSocket
            await this.connectWebSocket();

            // Start media recorder
            this.startMediaRecorder();

            // Update UI
            this.elements.startBtn.disabled = true;
            this.elements.stopBtn.disabled = false;
            this.updateStatus('Recording...', 'recording');

            // Start duration counter
            this.startTime = Date.now();
            this.durationInterval = setInterval(() => this.updateDuration(), 1000);

        } catch (error) {
            console.error('Failed to start:', error);
            alert('Failed to start: ' + error.message);
            this.stop();
        }
    }

    async connectWebSocket() {
        return new Promise((resolve, reject) => {
            const url = new URL(this.config.gatewayUrl);
            url.searchParams.set('api_key', this.config.apiKey);
            url.searchParams.set('language', this.config.language);
            url.searchParams.set('model', this.config.model);
            url.searchParams.set('enable_diarization', this.config.enableDiarization);

            this.ws = new WebSocket(url.toString());

            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.updateStatus('Connected', 'connected');
                resolve();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                reject(error);
            };

            this.ws.onclose = () => {
                console.log('WebSocket closed');
                this.updateStatus('Disconnected', 'disconnected');
            };

            this.ws.onmessage = (event) => {
                this.handleMessage(JSON.parse(event.data));
            };
        });
    }

    startMediaRecorder() {
        // Use WebM format (supported by most browsers)
        this.mediaRecorder = new MediaRecorder(this.audioStream, {
            mimeType: 'audio/webm;codecs=opus',
            audioBitsPerSecond: 128000
        });

        this.mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0 && this.ws && this.ws.readyState === WebSocket.OPEN) {
                // Send audio chunk to server
                this.ws.send(event.data);
            }
        };

        // Send chunks every 500ms for low latency
        this.mediaRecorder.start(500);
    }

    handleMessage(message) {
        console.log('Received message:', message.type, message);

        switch (message.type) {
            case 'session_started':
                this.sessionId = message.data.session_id;
                console.log('Session started:', this.sessionId);
                break;

            case 'interim':
                this.displayTranscript(message.data, true);
                break;

            case 'final':
                this.displayTranscript(message.data, false);
                if (message.data.latency_ms) {
                    this.elements.latency.textContent = message.data.latency_ms + 'ms';
                }
                break;

            case 'speaker':
                this.updateSpeakers(message.data);
                break;

            case 'error':
                console.error('Server error:', message.data.message);
                alert('Server error: ' + message.data.message);
                break;

            case 'session_ended':
                console.log('Session ended');
                break;
        }
    }

    displayTranscript(data, isInterim) {
        if (!data.segments || data.segments.length === 0) return;

        for (const segment of data.segments) {
            const segmentId = `segment-${segment.start}`;
            let segmentEl = document.getElementById(segmentId);

            if (!segmentEl) {
                segmentEl = document.createElement('div');
                segmentEl.id = segmentId;
                segmentEl.className = 'segment';
                this.elements.transcript.appendChild(segmentEl);
            }

            // Format timestamp
            const timestamp = this.formatTime(segment.start);

            // Build HTML
            let html = '';
            if (segment.speaker) {
                html += `<div class="speaker">${segment.speaker} <span class="timestamp">${timestamp}</span></div>`;
            } else {
                html += `<div class="timestamp">${timestamp}</div>`;
            }

            html += `<div class="text ${isInterim ? 'interim' : ''}">${segment.text}</div>`;

            segmentEl.innerHTML = html;

            // Update word count
            if (!isInterim) {
                this.wordCount += (segment.text.match(/\S+/g) || []).length;
                this.elements.wordCount.textContent = this.wordCount;
            }
        }

        // Scroll to bottom
        this.elements.transcript.scrollTop = this.elements.transcript.scrollHeight;
    }

    updateSpeakers(data) {
        // Update speaker information
        console.log('Speakers:', data.speakers);
    }

    formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    updateDuration() {
        if (!this.startTime) return;

        const elapsed = Math.floor((Date.now() - this.startTime) / 1000);
        this.elements.duration.textContent = this.formatTime(elapsed);
    }

    stop() {
        // Stop media recorder
        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            this.mediaRecorder.stop();
        }

        // Close WebSocket
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        // Stop audio stream
        if (this.audioStream) {
            this.audioStream.getTracks().forEach(track => track.stop());
            this.audioStream = null;
        }

        // Stop duration counter
        if (this.durationInterval) {
            clearInterval(this.durationInterval);
            this.durationInterval = null;
        }

        // Update UI
        this.elements.startBtn.disabled = false;
        this.elements.stopBtn.disabled = true;
        this.updateStatus('Disconnected', 'disconnected');
    }
}

// Initialize client when page loads
let client;
document.addEventListener('DOMContentLoaded', () => {
    client = new TranscriptionClient();
});
