import { useState } from 'react';
import { UserView } from './components/UserView';
import { DevView } from './components/DevView.tsx';
import { AdminView } from './components/AdminView.tsx';
import { Shield, Terminal, User } from 'lucide-react';
import { TabList, Tab } from '@fluentui/react-components';

type Role = 'User' | 'Dev' | 'Admin';

function App() {
  const [role, setRole] = useState<Role>('User');

  return (
    <div className="h-screen w-full bg-[#202020] text-white flex flex-col font-sans selection:bg-[#479ef5]/40 selection:text-white overflow-hidden">
      {/* Fluent 2 Title Bar / Header */}
      <header className="h-[48px] bg-[#202020]/70 backdrop-blur-[40px] border-b border-white/10 flex items-center justify-between px-4 shrink-0 z-20">
        <div className="flex items-center space-x-3 pointer-events-none">
          <div className="w-[18px] h-[18px] bg-[#479ef5] rounded flex items-center justify-center">
            <svg className="w-3 h-3 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="4 7 4 4 20 4 20 7" />
              <line x1="9" y1="20" x2="15" y2="20" />
              <line x1="12" y1="4" x2="12" y2="20" />
            </svg>
          </div>
          <span className="text-[12px] font-semibold text-white tracking-wide">Vanna Workspace</span>
        </div>

        {/* Fluent Pivot / Tab Control via @fluentui/react-components */}
        <div className="flex items-center h-full pt-1.5">
          <TabList 
            selectedValue={role} 
            onTabSelect={(_, data) => setRole(data.value as Role)}
            appearance="transparent"
            size="small"
          >
            <Tab value="User" icon={<User size={14} strokeWidth={2} />}>
              Analyst
            </Tab>
            <Tab value="Dev" icon={<Terminal size={14} strokeWidth={2} />}>
              Engineer
            </Tab>
            <Tab value="Admin" icon={<Shield size={14} strokeWidth={2} />}>
              Admin
            </Tab>
          </TabList>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 overflow-hidden flex flex-col relative z-0">
        {role === 'User' && <UserView />}
        {role === 'Dev' && <DevView />}
        {role === 'Admin' && <AdminView />}
      </main>
    </div>
  );
}

export default App;
