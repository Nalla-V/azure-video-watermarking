// --- START OF FINAL CORRECTED UploadForm.js ---
import React, { useState } from 'react';
import axios from 'axios';

function UploadForm({ setJobId, setAppMessage }) {
  const [videoFile, setVideoFile] = useState(null);
  const [watermarkFile, setWatermarkFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);

  const MAX_VIDEO_SIZE = 30 * 1024 * 1024; // 30 MB in bytes

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsUploading(true);
    setAppMessage({ text: 'Uploading...', type: 'processing' });
    setJobId('');

    // --- Validation Step 1: Check if files are selected ---
    if (!videoFile || !watermarkFile) {
      setAppMessage({ text: 'Please select both video and watermark files', type: 'error' });
      setIsUploading(false);
      return;
    }

    // --- THIS IS THE FIX: ADDED THE MISSING VALIDATION ---
    // --- Validation Step 2: Check video file size ---
    if (videoFile.size > MAX_VIDEO_SIZE) {
      setAppMessage({ text: 'Video file exceeds the 30 MB limit.', type: 'error' });
      setIsUploading(false);
      return;
    }
    // --- END OF FIX ---

    const newJobId = `job-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const formData = new FormData();
    formData.append('job_id', newJobId);
    formData.append('video', videoFile);
    formData.append('watermark', watermarkFile);

    try {
      await axios.post("https://watermarkflaskapi.azurewebsites.net/api/upload", formData);
      
      setJobId(newJobId);
      setAppMessage({ text: `Upload successful! Job ID: ${newJobId}`, type: 'success' });
    } catch (err) {
      setAppMessage({ text: err.response?.data?.error || 'Upload failed', type: 'error' });
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="section">
      <h2 className="form-title">
        <i className="fas fa-upload icon"></i> Upload Video and Watermark
      </h2>
      <form className="upload-form" onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="video">Video File (MP4, max 30 MB):</label>
          <input type="file" id="video" accept="video/mp4" onChange={(e) => setVideoFile(e.target.files[0])} disabled={isUploading} />
        </div>
        <div className="form-group">
          <label htmlFor="watermark">Watermark Image (PNG):</label>
          <input type="file" id="watermark" accept="image/png" onChange={(e) => setWatermarkFile(e.target.files[0])} disabled={isUploading} />
        </div>
        <button type="submit" className="submit-button" disabled={isUploading}>
          {isUploading ? 'Uploading...' : 'Upload'}
        </button>
      </form>
    </div>
  );
}

export default UploadForm;