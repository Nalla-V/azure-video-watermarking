import React, { useState } from 'react';

function DownloadResults() {
  const [jobId, setJobId] = useState('');
  const [error, setError] = useState('');
  const [jobStatus, setJobStatus] = useState(''); 
  const [isChecking, setIsChecking] = useState(false);
  
  const handleGetResults = async () => {
    setError('');
    setJobStatus('');
    if (!jobId) {
      setError('Please enter a Job ID.');
      return;
    }

    setIsChecking(true);
    try {
      const response = await fetch(`https://watermarkflaskapi.azurewebsites.net/api/status/${jobId}`);
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.error || 'Job ID not found or error fetching status.');
      }
      
      const data = await response.json();
      
      if (data.status && data.status.toLowerCase() === 'completed') {
        setJobStatus('completed');
      } else {
        setJobStatus(data.status);
        setError(`Job status is '${data.status}', not yet completed. Please wait and try again.`);
      }

    } catch (err) {
      setError(err.message || 'An error occurred while checking the job status.');
    } finally {
      setIsChecking(false);
    }
  };

  return (
    <div className="section">
      <h2 className="form-title">Download Results</h2>
      <div className="form-group">
        <label htmlFor="downloadJobId">Job ID:</label>
        <input
          type="text"
          id="downloadJobId"
          value={jobId}
          onChange={(e) => {
            setJobId(e.target.value);
            setJobStatus('');
            setError('');
          }}
          placeholder="Enter Job ID to download"
        />
      </div>
      
      <button 
        className="submit-button" 
        onClick={handleGetResults} 
        disabled={isChecking}
      >
        {isChecking ? 'Checking Status...' : 'Download Results'}
      </button>

      {error && <p className="status-message error">{error}</p>}
      
      {jobStatus === 'completed' && (
        <div className="download-links-container">
          <p className="status-message success">Job is complete! Click the links below to download:</p>
          
          {/* --- START OF UPDATED LINKS --- */}
          <a 
            href={`https://watermarkflaskapi.azurewebsites.net/api/download/${jobId}`} 
            className="download-link"
          >
            Download Watermarked Video (.mp4)
          </a>
          <a 
            href={`https://watermarkflaskapi.azurewebsites.net/api/thumbnail/${jobId}`}
            className="download-link"
          >
            Download Video Thumbnail (.png)
          </a>
          {/* --- END OF UPDATED LINKS --- */}
        </div>
      )}
    </div>
  );
}

export default DownloadResults;