import { useState } from 'react';
import { Settings, Shield, Link as LinkIcon, Activity, EyeOff, RefreshCw } from 'lucide-react';
import { Button, Input, Switch, Checkbox, Card, TabList, Tab } from '@fluentui/react-components';

export function AdminView() {
  const [activeMenu, setActiveMenu] = useState<'connections' | 'quality' | 'privacy'>('connections');
  const [isRestarting, setIsRestarting] = useState(false);

  const handleRestart = () => {
    setIsRestarting(true);
    // Simulate a fake server restart delay
    setTimeout(() => setIsRestarting(false), 2500);
  };

  return (
    <div className="flex flex-col h-full bg-[#202020]">
      <header className="px-8 py-6 bg-[#202020]/70 backdrop-blur-[40px] border-b border-white/10 flex items-center justify-between sticky top-0 z-10">
        <div>
          <h1 className="text-2xl font-semibold text-white flex items-center space-x-2">
            <Settings size={24} className="text-[#a6a6a6]" />
            <span>Settings</span>
          </h1>
        </div>
        
        <Button 
          onClick={handleRestart}
          disabled={isRestarting}
          icon={<RefreshCw size={14} className={isRestarting ? "animate-spin text-[#479ef5]" : ""} />}
          appearance={isRestarting ? "subtle" : "secondary"}
        >
          {isRestarting ? "Restarting Vanna Engine..." : "Restart Server"}
        </Button>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Fluent Standard Sidebar Navigation */}
        <aside className="w-[280px] bg-[#202020]/70 backdrop-blur-[40px] border-r border-white/10 flex flex-col pt-4 overflow-y-auto pl-2">
          <TabList
            selectedValue={activeMenu}
            onTabSelect={(_, data) => setActiveMenu(data.value as 'connections')}
            vertical
            appearance="transparent"
            size="medium"
          >
            <Tab value="connections" icon={<LinkIcon size={16} />}>Connections & Provider</Tab>
            <Tab value="quality" icon={<Activity size={16} />}>Data Observability</Tab>
            <Tab value="privacy" icon={<EyeOff size={16} />}>Privacy & Redaction</Tab>
          </TabList>
        </aside>

        {/* Settings Content Area */}
        <main className="flex-1 p-10 overflow-y-auto bg-[#202020]">
          {activeMenu === 'connections' && (
            <div className="max-w-2xl w-full">
              <h2 className="text-xl font-semibold mb-6 text-white">Service Connections</h2>
              
              <Card className="bg-[#2d2d2d] rounded-lg p-6 mb-8">
                <h3 className="text-[14px] font-semibold mb-4 text-white">Credentials</h3>
                <div className="space-y-4">
                  <div className="flex flex-col space-y-1">
                    <label className="text-[12px] text-[#a6a6a6]">Language Model API Key</label>
                    <Input type="password" placeholder="sk-..." />
                  </div>
                  <div className="flex flex-col space-y-1">
                    <label className="text-[12px] text-[#a6a6a6]">DataHub Metadata Endpoint</label>
                    <Input type="text" placeholder="https://..." defaultValue="http://datahub-gms:8080/graphql" />
                  </div>
                </div>
              </Card>
              
              <Card className="bg-[#2d2d2d] rounded-lg p-6">
                <h3 className="text-[14px] font-semibold mb-4 text-white">Data Warehouse Setup</h3>
                <div className="flex flex-col space-y-1">
                  <label className="text-[12px] text-[#a6a6a6]">Connection String (DSN)</label>
                  <Input type="password" placeholder="postgresql://..." />
                </div>
                <div className="mt-4">
                  <Button appearance="secondary" size="small">Test Connection</Button>
                </div>
              </Card>
            </div>
          )}

          {activeMenu === 'quality' && (
            <div className="max-w-2xl w-full">
               <h2 className="text-xl font-semibold mb-6 text-white flex items-center space-x-2">
                 <Shield className="text-[#479ef5]" size={20} />
                 <span>Observability Engine</span>
               </h2>
               
               <Card className="bg-[#2d2d2d] rounded-lg p-6 mb-8">
                 <p className="text-[13px] text-[#a6a6a6] mb-6">Configure the Great Expectations gatekeeper constraints before allowing execution workflows.</p>
                 
                 <div className="flex items-center justify-between mb-6 border-b border-white/10 pb-4">
                   <div>
                     <span className="text-[14px] font-semibold block text-white">Enable strict checking</span>
                     <span className="text-[13px] text-[#a6a6a6]">Halt processes on data degradation.</span>
                   </div>
                   <Switch defaultChecked={true} />
                 </div>
                 
                 <div className="flex flex-col space-y-1">
                    <label className="text-[12px] text-[#a6a6a6]">GX Configuration Token</label>
                    <Input type="password" defaultValue="gxc_auth_..." />
                 </div>
               </Card>
            </div>
          )}

          {activeMenu === 'privacy' && (
             <div className="max-w-2xl w-full">
                <h2 className="text-xl font-semibold mb-6 flex items-center space-x-2 text-white">
                 <EyeOff className="text-[#479ef5]" size={20} />
                 <span>Privacy Subsystem</span>
               </h2>

               <Card className="bg-[#2d2d2d] rounded-lg p-6">
                 <p className="text-[13px] text-[#a6a6a6] mb-6">
                   Select the entities to identify and strip structurally via Presidio prior to payload dispatch.
                 </p>
                 
                 <div className="grid grid-cols-2 gap-4">
                   {['CREDIT_CARD', 'EMAIL_ADDRESS', 'US_SSN', 'PERSON'].map(entity => (
                     <Checkbox key={entity} label={entity} defaultChecked={true} />
                   ))}
                   <Checkbox label={'IP_ADDRESS'} defaultChecked={false} />
                   <Checkbox label={'CRYPTO_WALLET'} defaultChecked={false} />
                 </div>
                 
                 <div className="mt-6">
                   <Button appearance="secondary" size="small">+ Add Regular Expression Matcher</Button>
                 </div>
               </Card>
             </div>
          )}
        </main>
      </div>
    </div>
  );
}
