// --- START OF FINAL CORRECTED App.js ---
import React, { useState } from 'react';
import UploadForm from './UploadForm';
import StatusChecker from './StatusChecker';
import DownloadResults from './DownloadResults';
import './index.css';

function App() {
  const [jobId, setJobId] = useState('');
  // A single, central place for all messages (errors, success, info)
  const [appMessage, setAppMessage] = useState({ text: '', type: '' });

  return (
    <div className="container">
      <div className="header">
        <img src="/assets/logo.png" alt="Logo" className="logo" />
        <h1 className="app-title">Watermarking as a Service</h1>
      </div>

      <UploadForm setJobId={setJobId} setAppMessage={setAppMessage} />
      
      {/* Display the central message */}
      {appMessage.text && 
        <p className={`status-message ${appMessage.type}`}>
          {appMessage.text}
        </p>
      }
      
      <hr className="divider" />
      
      <StatusChecker jobId={jobId} />
      
      <hr className="divider" />
      
      <DownloadResults />
    </div>
  );
}

export default App;