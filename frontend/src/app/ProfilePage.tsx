import React, { useState, useEffect } from 'react'
import { userAPI, authAPI } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

type ReactChangeEvent = React.ChangeEvent<HTMLInputElement>

interface UserProfile {
  id: number
  email: string
  first_name: string
  last_name: string
  created_at: string
  token_usage_count: number
}

interface TokenStats {
  total_tokens: number
  tokens_this_month: number
  tokens_last_30_days: number
  account_created: string
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [stats, setStats] = useState<TokenStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [saving, setSaving] = useState(false)

  // Password change form
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [changingPassword, setChangingPassword] = useState(false)

  useEffect(() => {
    loadProfile()
    loadStats()
  }, [])

  const loadProfile = async () => {
    try {
      const response = await userAPI.getCurrentUser()
      setProfile(response.data)
      setFirstName(response.data.first_name || '')
      setLastName(response.data.last_name || '')
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to load profile')
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const response = await userAPI.getUserStats()
      setStats(response.data)
    } catch (error: any) {
      console.error('Failed to load stats:', error)
    }
  }

  const handleSaveProfile = async () => {
    setSaving(true)
    try {
      const response = await userAPI.updateCurrentUser({
        first_name: firstName,
        last_name: lastName,
      })
      setProfile(response.data.user)
      setEditing(false)
      toast.success('Profile updated successfully')
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to update profile')
    } finally {
      setSaving(false)
    }
  }

  const handleChangePassword = async () => {
    if (newPassword !== confirmPassword) {
      toast.error('Passwords do not match')
      return
    }

    if (newPassword.length < 8) {
      toast.error('Password must be at least 8 characters long')
      return
    }

    setChangingPassword(true)
    try {
      await authAPI.changePassword({
        old_password: oldPassword,
        new_password: newPassword,
      })
      toast.success('Password changed successfully')
      setOldPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (error: any) {
      toast.error(error.response?.data?.error || 'Failed to change password')
    } finally {
      setChangingPassword(false)
    }
  }

  if (loading) {
    return <div className="text-center py-8">Loading...</div>
  }

  if (!profile) {
    return <div className="text-center py-8">Failed to load profile</div>
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h1 className="text-3xl font-bold">Profile</h1>

      {/* Token Usage Section */}
      {stats && (
        <div className="border rounded-lg p-6">
          <h2 className="text-xl font-semibold mb-4">Token Usage</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-sm font-medium text-muted-foreground">Total Tokens</label>
              <p className="text-2xl font-bold">{stats.total_tokens.toLocaleString()}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-muted-foreground">This Month</label>
              <p className="text-2xl font-bold">{stats.tokens_this_month.toLocaleString()}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-muted-foreground">Last 30 Days</label>
              <p className="text-2xl font-bold">{stats.tokens_last_30_days.toLocaleString()}</p>
            </div>
          </div>
        </div>
      )}

      {/* Basic Information Section */}
      <div className="border rounded-lg p-6">
        <h2 className="text-xl font-semibold mb-4">Basic Information</h2>
        {!editing ? (
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-muted-foreground">Email</label>
              <p className="text-base">{profile.email}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-muted-foreground">First Name</label>
              <p className="text-base">{profile.first_name || 'Not set'}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-muted-foreground">Last Name</label>
              <p className="text-base">{profile.last_name || 'Not set'}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-muted-foreground">Account Created</label>
              <p className="text-base">{new Date(profile.created_at).toLocaleDateString()}</p>
            </div>
            <Button onClick={() => setEditing(true)} className="mt-4">
              Edit Profile
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Email</label>
              <input
                type="email"
                value={profile.email}
                disabled
                className="w-full px-3 py-2 border rounded-md bg-muted"
              />
              <p className="text-xs text-muted-foreground mt-1">Email cannot be changed</p>
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">First Name</label>
              <input
                type="text"
                value={firstName}
                onChange={(e: ReactChangeEvent) => setFirstName(e.target.value)}
                className="w-full px-3 py-2 border rounded-md"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Last Name</label>
              <input
                type="text"
                value={lastName}
                onChange={(e: ReactChangeEvent) => setLastName(e.target.value)}
                className="w-full px-3 py-2 border rounded-md"
              />
            </div>
            <div className="flex gap-2">
              <Button onClick={handleSaveProfile} disabled={saving}>
                {saving ? 'Saving...' : 'Save Changes'}
              </Button>
              <Button variant="outline" onClick={() => {
                setEditing(false)
                setFirstName(profile.first_name || '')
                setLastName(profile.last_name || '')
              }}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Change Password Section */}
      <div className="border rounded-lg p-6">
        <h2 className="text-xl font-semibold mb-4">Change Password</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">Current Password</label>
            <input
              type="password"
              value={oldPassword}
              onChange={(e: ReactChangeEvent) => setOldPassword(e.target.value)}
              className="w-full px-3 py-2 border rounded-md"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">New Password</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e: ReactChangeEvent) => setNewPassword(e.target.value)}
              className="w-full px-3 py-2 border rounded-md"
              minLength={8}
            />
            <p className="text-xs text-muted-foreground mt-1">Must be at least 8 characters</p>
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Confirm New Password</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e: ReactChangeEvent) => setConfirmPassword(e.target.value)}
              className="w-full px-3 py-2 border rounded-md"
              minLength={8}
            />
          </div>
          <Button onClick={handleChangePassword} disabled={changingPassword}>
            {changingPassword ? 'Changing...' : 'Change Password'}
          </Button>
        </div>
      </div>
    </div>
  )
}
