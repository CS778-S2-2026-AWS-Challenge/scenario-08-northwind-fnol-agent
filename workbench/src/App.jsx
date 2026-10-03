import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext.jsx'
import ProtectedRoute from './auth/ProtectedRoute.jsx'
import AccountSettingsPage from './pages/AccountSettingsPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import WorkbenchPage from './pages/WorkbenchPage.jsx'

function ProtectedWorkbench() {
  return <ProtectedRoute><WorkbenchPage /></ProtectedRoute>
}

function ProtectedSettings() {
  return <ProtectedRoute><AccountSettingsPage /></ProtectedRoute>
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/workbench/login" element={<LoginPage />} />
        <Route path="/workbench/settings" element={<Navigate to="/workbench/settings/profile" replace />} />
        <Route path="/workbench/settings/:settingsSection" element={<ProtectedSettings />} />
        <Route path="/workbench" element={<ProtectedWorkbench />} />
        <Route path="/workbench/conversations" element={<ProtectedWorkbench />} />
        <Route path="/workbench/conversations/:conversationSessionId" element={<ProtectedWorkbench />} />
        <Route path="/workbench/agent/sessions/:agentSessionId" element={<ProtectedWorkbench />} />
        <Route path="/workbench/active" element={<ProtectedWorkbench />} />
        <Route path="/workbench/active/claims/:claimId" element={<ProtectedWorkbench />} />
        <Route path="/workbench/active/claims/:claimId/:section" element={<ProtectedWorkbench />} />
        <Route path="/workbench/drafts" element={<ProtectedWorkbench />} />
        <Route path="/workbench/drafts/:claimId" element={<ProtectedWorkbench />} />
        <Route path="/workbench/drafts/:claimId/:section" element={<ProtectedWorkbench />} />
        <Route path="/workbench/claims/:claimId" element={<ProtectedWorkbench />} />
        <Route path="/workbench/claims/:claimId/:section" element={<ProtectedWorkbench />} />
        <Route path="*" element={<Navigate to="/workbench" replace />} />
      </Routes>
    </AuthProvider>
  )
}
