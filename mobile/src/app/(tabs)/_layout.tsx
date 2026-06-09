import React from 'react';
import { Tabs } from 'expo-router';
import { TabBar } from '@/components/TabBar';

export default function TabsLayout() {
  return (
    <Tabs
      tabBar={(props) => <TabBar {...props} />}
      screenOptions={{ headerShown: false, sceneStyle: { backgroundColor: 'transparent' } }}
    >
      <Tabs.Screen name="home" />
      <Tabs.Screen name="portfolios" />
      <Tabs.Screen name="markets" />
      <Tabs.Screen name="orders" />
      <Tabs.Screen name="settings" />
    </Tabs>
  );
}
