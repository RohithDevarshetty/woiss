/**
 * Voice Synthesis Client
 * Handles voice profile creation and speech synthesis
 */

const API_BASE = 'http://localhost:8002';
let profiles = [];
let currentAudioBlob = null;

// Tab switching
function switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.remove('active');
    });
    event.target.classList.add('active');

    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(`${tabName}-tab`).classList.add('active');

    // Load profiles when switching to manage tab
    if (tabName === 'manage') {
        loadProfiles();
    }

    // Load speaker options when switching to synthesize tab
    if (tabName === 'synthesize') {
        loadSpeakerOptions();
    }
}

// Create Voice Profile
async function createVoiceProfile() {
    const userId = document.getElementById('userId').value;
    const profileName = document.getElementById('profileName').value;
    const profileDescription = document.getElementById('profileDescription').value;
    const audioFile = document.getElementById('audioFile').files[0];
    const resultDiv = document.getElementById('createResult');

    // Validation
    if (!userId) {
        showResult(resultDiv, 'error', 'Please enter your User ID');
        return;
    }

    if (!profileName) {
        showResult(resultDiv, 'error', 'Please enter a profile name');
        return;
    }

    if (!audioFile) {
        showResult(resultDiv, 'error', 'Please select an audio file');
        return;
    }

    // Show loading
    showResult(resultDiv, 'info', 'Creating voice profile... <span class="loading"></span>');

    try {
        // Create form data
        const formData = new FormData();
        formData.append('name', profileName);
        formData.append('description', profileDescription);
        formData.append('user_id', userId);
        formData.append('audio', audioFile);

        // Send request
        const response = await fetch(`${API_BASE}/v1/voice-profiles`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create profile');
        }

        const result = await response.json();

        // Show success
        showResult(resultDiv, 'success', `
            <strong>Voice profile created successfully!</strong><br>
            Profile ID: ${result.id}<br>
            Embedding Key: ${result.embedding_key}<br>
            Embedding Dimensions: ${result.embedding_dims}<br>
            <br>
            <strong>⚠️ Important:</strong> Consent verification is required before you can use this profile for synthesis.
            <button class="btn-primary" onclick="verifyConsent('${result.id}')">Verify Consent Now</button>
        `);

        // Clear form
        document.getElementById('profileName').value = '';
        document.getElementById('profileDescription').value = '';
        document.getElementById('audioFile').value = '';

    } catch (error) {
        showResult(resultDiv, 'error', `Failed to create voice profile: ${error.message}`);
    }
}

// Verify Consent
async function verifyConsent(profileId) {
    const signature = prompt('Enter your consent signature (type "I CONSENT"):');

    if (!signature) {
        return;
    }

    if (signature !== 'I CONSENT') {
        alert('Invalid consent signature. Please type exactly: I CONSENT');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/v1/voice-profiles/${profileId}/consent`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                signature: btoa(signature) // Base64 encode
            })
        });

        if (!response.ok) {
            throw new Error('Failed to verify consent');
        }

        alert('Consent verified successfully! You can now use this profile for synthesis.');
        loadProfiles(); // Refresh profile list

    } catch (error) {
        alert(`Failed to verify consent: ${error.message}`);
    }
}

// Load Speaker Options for Synthesis
async function loadSpeakerOptions() {
    try {
        const response = await fetch(`${API_BASE}/v1/voice-profiles`);

        if (!response.ok) {
            throw new Error('Failed to load profiles');
        }

        profiles = await response.json();

        // Populate select dropdown
        const select = document.getElementById('speakerSelect');
        select.innerHTML = '<option value="">-- Select a voice profile --</option>';

        profiles.forEach(profile => {
            if (profile.consent_verified) {
                const option = document.createElement('option');
                option.value = profile.id;
                option.textContent = `${profile.name} (${profile.id.substring(0, 8)}...)`;
                select.appendChild(option);
            }
        });

    } catch (error) {
        console.error('Failed to load speaker options:', error);
    }
}

// Synthesize Speech
async function synthesizeSpeech() {
    const speakerId = document.getElementById('speakerSelect').value;
    const text = document.getElementById('synthesisText').value;
    const language = document.getElementById('synthesisLanguage').value;
    const resultDiv = document.getElementById('synthesisResult');
    const audioContainer = document.getElementById('audioPlayerContainer');

    // Validation
    if (!speakerId) {
        showResult(resultDiv, 'error', 'Please select a voice profile');
        return;
    }

    if (!text) {
        showResult(resultDiv, 'error', 'Please enter text to synthesize');
        return;
    }

    // Show loading
    showResult(resultDiv, 'info', 'Generating speech... This may take a few moments. <span class="loading"></span>');
    audioContainer.classList.add('hidden');

    try {
        // Send synthesis request
        const response = await fetch(`${API_BASE}/v1/synthesize`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                text: text,
                speaker_id: speakerId,
                language: language
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Synthesis failed');
        }

        // Get audio blob
        const audioBlob = await response.blob();
        currentAudioBlob = audioBlob;

        // Create audio URL
        const audioUrl = URL.createObjectURL(audioBlob);

        // Update audio player
        const audioPlayer = document.getElementById('audioPlayer');
        audioPlayer.src = audioUrl;

        // Show success
        showResult(resultDiv, 'success', `
            <strong>Speech generated successfully!</strong><br>
            Audio size: ${(audioBlob.size / 1024).toFixed(2)} KB<br>
            You can play or download the audio below.
        `);

        // Show audio player
        audioContainer.classList.remove('hidden');

        // Auto-play
        audioPlayer.play();

    } catch (error) {
        showResult(resultDiv, 'error', `Synthesis failed: ${error.message}`);
    }
}

// Download Audio
function downloadAudio() {
    if (!currentAudioBlob) {
        alert('No audio to download');
        return;
    }

    const url = URL.createObjectURL(currentAudioBlob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `synthesis_${Date.now()}.wav`;
    a.click();

    URL.revokeObjectURL(url);
}

// Load Profiles
async function loadProfiles() {
    const userId = document.getElementById('manageUserId').value;
    const profileListDiv = document.getElementById('profileList');

    profileListDiv.innerHTML = '<p>Loading profiles...</p>';

    try {
        let url = `${API_BASE}/v1/voice-profiles`;
        if (userId) {
            url += `?user_id=${encodeURIComponent(userId)}`;
        }

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error('Failed to load profiles');
        }

        profiles = await response.json();

        if (profiles.length === 0) {
            profileListDiv.innerHTML = '<p>No voice profiles found.</p>';
            return;
        }

        // Display profiles
        profileListDiv.innerHTML = '';

        profiles.forEach(profile => {
            const card = document.createElement('div');
            card.className = 'profile-card';
            card.innerHTML = `
                <div class="profile-name">${escapeHtml(profile.name)}</div>
                <div class="profile-description">${escapeHtml(profile.description || 'No description')}</div>
                <div class="profile-meta">
                    <span>ID: ${profile.id.substring(0, 8)}...</span>
                    <span class="consent-badge ${profile.consent_verified ? 'consent-verified' : 'consent-pending'}">
                        ${profile.consent_verified ? '✓ Consent Verified' : '⚠ Consent Pending'}
                    </span>
                </div>
                <div class="profile-meta" style="margin-top: 8px;">
                    <span>Created: ${new Date(profile.created_at).toLocaleDateString()}</span>
                </div>
                <div class="profile-actions">
                    ${!profile.consent_verified ? `
                        <button class="btn-primary" onclick="verifyConsent('${profile.id}')">Verify Consent</button>
                    ` : ''}
                    <button class="btn-danger" onclick="deleteProfile('${profile.id}')">Delete</button>
                </div>
            `;
            profileListDiv.appendChild(card);
        });

    } catch (error) {
        profileListDiv.innerHTML = `<p style="color: #ef4444;">Failed to load profiles: ${error.message}</p>`;
    }
}

// Delete Profile
async function deleteProfile(profileId) {
    if (!confirm('Are you sure you want to delete this voice profile? This action cannot be undone.')) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/v1/voice-profiles/${profileId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error('Failed to delete profile');
        }

        alert('Profile deleted successfully');
        loadProfiles(); // Refresh list

    } catch (error) {
        alert(`Failed to delete profile: ${error.message}`);
    }
}

// Helper Functions
function showResult(element, type, message) {
    element.className = `alert alert-${type}`;
    element.innerHTML = message;
    element.classList.remove('hidden');
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    console.log('Voice Synthesis Client Initialized');
});
