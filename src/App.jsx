import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppShell from './components/shell/AppShell.jsx'
import LiveIncidents from './pages/LiveIncidents.jsx'
import MapView from './pages/MapView.jsx'
import RoadSigns from './pages/RoadSigns.jsx'
import Devices from './pages/Devices.jsx'
import HardwareUnits from './pages/HardwareUnits.jsx'
import AdminStakeholders from './pages/admin/Stakeholders.jsx'
import AdminRules from './pages/admin/Rules.jsx'
import AdminEscalation from './pages/admin/EscalationPolicies.jsx'
import AdminTemplates from './pages/admin/Templates.jsx'
import AdminRoadSignBoards from './pages/admin/RoadSignBoards.jsx'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/incidents" replace />} />
          <Route path="/incidents" element={<LiveIncidents />} />
          <Route path="/map" element={<MapView />} />
          <Route path="/road-signs" element={<RoadSigns />} />
          <Route path="/devices" element={<Devices />} />
          <Route path="/hardware" element={<HardwareUnits />} />
          <Route path="/admin/stakeholders" element={<AdminStakeholders />} />
          <Route path="/admin/rules" element={<AdminRules />} />
          <Route path="/admin/escalation" element={<AdminEscalation />} />
          <Route path="/admin/templates" element={<AdminTemplates />} />
          <Route path="/admin/road-signs" element={<AdminRoadSignBoards />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
