// --- START OF CORRECTED FILE StatusChecker.js ---
import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

function StatusChecker({ initialJobId }) {
  const [jobId, setJobId] = useState('');
  const [statusData, setStatusData] = useState(null);
  const [error, setError] = useState('');
  const [isPolling, setIsPolling] = useState(false);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (initialJobId) {
      setJobId(initialJobId);
      // Start polling automatically after a fresh upload
      handleCheckStatus(initialJobId, true);
    }
  }, [initialJobId]);

  const handleCheckStatus = async (idToCheck, startPolling = false) => {
    if (!idToCheck) return;

    // --- THIS IS THE FIX ---
    // Clear BOTH previous success data and errors at the start of a new request.
    setStatusData(null);
    setError('');
    // --- END OF FIX ---

    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }

    const check = async () => {
      setIsPolling(true);
      try {
        const response = await axios.get(`https://watermarkflaskapi.azurewebsites.net/api/status/${idToCheck}`);
        // When we get a new result, clear any lingering errors
        setError(''); 
        setStatusData(response.data);

        if (response.data.status === 'complete' || response.data.status === 'failed') {
          if (intervalRef.current) {
            clearInterval(intervalRef.current);
          }
        }
      } catch (err) {
        // When we get an error, clear any lingering success data
        setStatusData(null); 
        setError(err.response?.data?.error || 'Error checking status');
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
        }
      } finally {
        setIsPolling(false);
      }
    };

    check(); // Check immediately
    if (startPolling) {
      intervalRef.current = setInterval(check, 5000);
    }
  };

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const onButtonClick = () => {
    // A manual button click should trigger a single check, not a polling loop.
    handleCheckStatus(jobId, false);
  };

  return (
    <div className="section">
      <h2 className="form-title">Check Job Status</h2>
      <div className="form-group">
        <label htmlFor="statusJobId">Job ID:</label>
        <input
          type="text"
          id="statusJobId"
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          placeholder="Enter Job ID to check status"
        />
      </div>
      <button className="submit-button" onClick={onButtonClick} disabled={isPolling}>
        {isPolling ? 'Checking...' : 'Check Status'}
      </button>
      {/* These two are now mutually exclusive because we clear the other's state */}
      {statusData && (
        <div className="status-message">
          <p>Current Status: <strong className={statusData.status}>{statusData.status}</strong></p>
        </div>
      )}
      {error && <p className="status-message error">{error}</p>}
    </div>
  );
}

export default StatusChecker;