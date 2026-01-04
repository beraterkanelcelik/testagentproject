import React from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import Layout from '@/components/Layout'
import HomePage from '@/app/HomePage'
import LoginPage from '@/app/auth/LoginPage'
import SignupPage from '@/app/auth/SignupPage'
import DashboardPage from '@/app/DashboardPage'
import ProfilePage from '@/app/ProfilePage'
import ChatPage from '@/app/chat/ChatPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="signup" element={<SignupPage />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="chat/:sessionId?" element={<ChatPage />} />
        </Route>
      </Routes>
      <Toaster position="top-right" />
    </BrowserRouter>
  )
}

export default App
