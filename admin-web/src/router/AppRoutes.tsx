import { Navigate, Route, Routes } from 'react-router-dom'

import AdminLayout from '../layouts/AdminLayout'
import AppointmentsPage from '../pages/admin/AppointmentsPage'
import CourseManagePage from '../pages/admin/CourseManagePage'
import GiftManagePage from '../pages/admin/GiftManagePage'
import LegacyUserCoursePage from '../pages/admin/LegacyUserCoursePage'
import LessonManagePage from '../pages/admin/LessonManagePage'
import LoginPage from '../pages/admin/LoginPage'
import MediaManagePage from '../pages/admin/MediaManagePage'
import OrderManagePage from '../pages/admin/OrderManagePage'
import RemoteVodLibraryPage from '../pages/admin/RemoteVodLibraryPage'
import SysConfigPage from '../pages/admin/SysConfigPage'
import UserCourseManagePage from '../pages/admin/UserCourseManagePage'
import RequireAuth from './RequireAuth'

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route element={<RequireAuth />}>
        <Route path="/" element={<AdminLayout />}>
          <Route index element={<Navigate to="/courses" replace />} />
          <Route path="courses" element={<CourseManagePage />} />
          <Route path="lessons" element={<LessonManagePage />} />
          <Route path="media" element={<MediaManagePage />} />
          <Route path="media/vod-library" element={<RemoteVodLibraryPage />} />
          <Route path="gifts" element={<GiftManagePage />} />
          <Route path="orders" element={<OrderManagePage />} />
          <Route path="user-course" element={<UserCourseManagePage />} />
          <Route path="appointments" element={<AppointmentsPage />} />
          <Route path="user-courses" element={<LegacyUserCoursePage />} />
          <Route path="config" element={<SysConfigPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
