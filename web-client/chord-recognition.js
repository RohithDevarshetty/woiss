/**
 * Piano Chord Recognition Client
 * Upload music and view extracted chords/notes
 */

const API_BASE = 'http://localhost:8003';
let currentAudioFile = null;
let analysisResults = null;

// File upload handling
const uploadArea = document.getElementById('uploadArea');
const audioFile = document.getElementById('audioFile');
const analyzeBtn = document.getElementById('analyzeBtn');

// Drag and drop
uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('dragging');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragging');
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('dragging');

    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFileSelect(files[0]);
    }
});

// File input change
audioFile.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFileSelect(e.target.files[0]);
    }
});

function handleFileSelect(file) {
    currentAudioFile = file;

    // Show file info
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('fileSize').textContent = formatFileSize(file.size);
    document.getElementById('fileInfo').classList.remove('hidden');

    // Enable analyze button
    analyzeBtn.disabled = false;

    // Show audio player
    const audioPlayer = document.getElementById('audioPlayer');
    const url = URL.createObjectURL(file);
    audioPlayer.src = url;
    document.getElementById('audioPlayerCard').classList.remove('hidden');
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

// Analyze music
async function analyzeMusic() {
    if (!currentAudioFile) {
        alert('Please select a music file first');
        return;
    }

    const statusDiv = document.getElementById('processingStatus');
    statusDiv.className = 'alert alert-info';
    statusDiv.innerHTML = '<strong>Analyzing...</strong> Extracting chords and notes from your music. This may take a minute. <span class="loading"></span>';
    statusDiv.classList.remove('hidden');

    analyzeBtn.disabled = true;

    try {
        // Create form data
        const formData = new FormData();
        formData.append('audio', currentAudioFile);

        // Send request
        const response = await fetch(`${API_BASE}/v1/recognize`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Analysis failed');
        }

        analysisResults = await response.json();

        // Show success
        statusDiv.className = 'alert alert-success';
        statusDiv.innerHTML = '<strong>Analysis complete!</strong> Scroll down to view the results.';

        // Display results
        displayResults(analysisResults);

    } catch (error) {
        statusDiv.className = 'alert alert-error';
        statusDiv.innerHTML = `<strong>Error:</strong> ${error.message}`;
    } finally {
        analyzeBtn.disabled = false;
    }
}

function displayResults(results) {
    // Show results card
    document.getElementById('resultsCard').classList.remove('hidden');

    // Update stats
    document.getElementById('duration').textContent = results.duration.toFixed(2) + 's';
    document.getElementById('tempo').textContent = Math.round(results.tempo);
    document.getElementById('key').textContent = results.key;
    document.getElementById('timeSignature').textContent = results.time_signature;
    document.getElementById('notesCount').textContent = results.notes.length;
    document.getElementById('chordsCount').textContent = results.chords.length;

    // Display sheet music
    if (results.sheet_music && results.sheet_music.length > 0) {
        document.getElementById('sheetMusicCard').classList.remove('hidden');
        const sheetDiv = document.getElementById('sheetMusic');
        sheetDiv.textContent = results.sheet_music.join('\n\n');
    }

    // Display chord progression
    if (results.chords && results.chords.length > 0) {
        document.getElementById('chordsCard').classList.remove('hidden');
        displayChordProgression(results.chords);
    }

    // Display notes
    if (results.notes && results.notes.length > 0) {
        document.getElementById('notesCard').classList.remove('hidden');
        displayNotes(results.notes);
    }
}

function displayChordProgression(chords) {
    const timeline = document.getElementById('chordTimeline');
    timeline.innerHTML = '';

    chords.forEach(chord => {
        const bar = document.createElement('div');
        bar.className = 'chord-bar';

        const name = document.createElement('span');
        name.className = 'chord-name';
        name.textContent = chord.chord;

        const time = document.createElement('span');
        time.className = 'chord-time';
        time.textContent = `${formatTime(chord.start)} - ${formatTime(chord.end)}`;

        bar.appendChild(name);
        bar.appendChild(time);
        timeline.appendChild(bar);
    });
}

function displayNotes(notes) {
    const grid = document.getElementById('notesGrid');
    grid.innerHTML = '';

    // Show first 50 notes (to avoid overwhelming the UI)
    const displayNotes = notes.slice(0, 50);

    displayNotes.forEach(note => {
        const card = document.createElement('div');
        card.className = 'note-card';

        const name = document.createElement('div');
        name.className = 'note-name';
        name.textContent = note.note;

        const info = document.createElement('div');
        info.className = 'note-info';

        const duration = note.duration || (note.end - note.start);

        info.innerHTML = `
            <p><strong>Time:</strong> ${formatTime(note.start)} - ${formatTime(note.end)}</p>
            <p><strong>Duration:</strong> ${duration.toFixed(2)}s</p>
            <p><strong>Frequency:</strong> ${note.frequency.toFixed(1)} Hz</p>
            <p><strong>MIDI:</strong> ${note.midi}</p>
            <p><strong>Confidence:</strong> ${(note.confidence * 100).toFixed(1)}%</p>
            ${note.chord_notes ? `<p><strong>Chord:</strong> ${note.chord_notes.join(', ')}</p>` : ''}
        `;

        card.appendChild(name);
        card.appendChild(info);
        grid.appendChild(card);
    });

    if (notes.length > 50) {
        const more = document.createElement('div');
        more.className = 'note-card';
        more.style.background = '#e5e7eb';
        more.innerHTML = `<p style="text-align: center; color: #6b7280;">+ ${notes.length - 50} more notes</p>`;
        grid.appendChild(more);
    }
}

function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return `${mins}:${secs.padStart(4, '0')}`;
}

function copySheetMusic() {
    const sheetText = document.getElementById('sheetMusic').textContent;

    navigator.clipboard.writeText(sheetText).then(() => {
        alert('Sheet music copied to clipboard!');
    }).catch(err => {
        console.error('Failed to copy:', err);
        alert('Failed to copy to clipboard');
    });
}

// Download results as JSON
function downloadResults() {
    if (!analysisResults) {
        alert('No results to download');
        return;
    }

    const blob = new Blob([JSON.stringify(analysisResults, null, 2)], {
        type: 'application/json'
    });

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'chord-analysis.json';
    a.click();

    URL.revokeObjectURL(url);
}

// Initialize
console.log('Piano Chord Recognition Client loaded');
