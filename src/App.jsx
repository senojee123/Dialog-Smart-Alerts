import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppShell from './components/shell/AppShell.jsx'
import ErrorBoundary from './components/common/ErrorBoundary.jsx'
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

function Wrap({ children }) {
  return <ErrorBoundary>{children}</ErrorBoundary>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/incidents" replace />} />
          <Route path="/incidents" element={<Wrap><LiveIncidents /></Wrap>} />
          <Route path="/map" element={<Wrap><MapView /></Wrap>} />
          <Route path="/road-signs" element={<Wrap><RoadSigns /></Wrap>} />
          <Route path="/devices" element={<Wrap><Devices /></Wrap>} />
          <Route path="/hardware" element={<Wrap><HardwareUnits /></Wrap>} />
          <Route path="/admin/stakeholders" element={<Wrap><AdminStakeholders /></Wrap>} />
          <Route path="/admin/rules" element={<Wrap><AdminRules /></Wrap>} />
          <Route path="/admin/escalation" element={<Wrap><AdminEscalation /></Wrap>} />
          <Route path="/admin/templates" element={<Wrap><AdminTemplates /></Wrap>} />
          <Route path="/admin/road-signs" element={<Wrap><AdminRoadSignBoards /></Wrap>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
