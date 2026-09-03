import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext.jsx'
import ProtectedRoute from './auth/ProtectedRoute.jsx'
import LoginPage from './pages/LoginPage.jsx'
import WorkbenchPage from './pages/WorkbenchPage.jsx'

function ProtectedWorkbench() {
  return <ProtectedRoute><WorkbenchPage /></ProtectedRoute>
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/workbench/login" element={<LoginPage />} />
        <Route path="/workbench" element={<ProtectedWorkbench />} />
        <Route path="/workbench/conversations" element={<ProtectedWorkbench />} />
        <Route path="/workbench/conversations/:conversationSessionId" element={<ProtectedWorkbench />} />
        <Route path="/workbench/agent/sessions/:agentSessionId" element={<ProtectedWorkbench />} />
        <Route path="/workbench/claims/:claimId" element={<ProtectedWorkbench />} />
        <Route path="/workbench/claims/:claimId/:section" element={<ProtectedWorkbench />} />
        <Route path="*" element={<Navigate to="/workbench" replace />} />
      </Routes>
    </AuthProvider>
  )
}
