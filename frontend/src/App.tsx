import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from '@/components/auth/protected-route'
import { HomePage } from '@/pages/home-page'
import { SignInPage } from '@/pages/sign-in-page'

function App() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignInPage />} />
      <Route element={<ProtectedRoute />}>
        <Route index element={<HomePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
