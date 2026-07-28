@description('Name of the Microsoft Foundry (Cognitive Services) account.')
param accountName string

@description('Name of the Foundry project that hosts the agent and the A2A connection.')
param projectName string

param location string
param tags object = {}

@description('Object ID granted Foundry User on the account. Empty skips the role assignment.')
param principalId string = ''

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

param modelName string
param modelVersion string = ''
param modelCapacity int
param modelDeploymentName string
param modelSkuName string = 'GlobalStandard'

// Foundry User (formerly Azure AI User): build and run agents in the project.
var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    // Required so the account can host Foundry projects.
    allowProjectManagement: true
    // A custom subdomain is required for Entra ID token authentication.
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Work IQ A2A sample'
    description: 'Hosts the coordinator agent that calls Microsoft Work IQ over A2A.'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-05-01' = {
  parent: account
  name: modelDeploymentName
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  properties: {
    model: union(
      {
        format: 'OpenAI'
        name: modelName
      },
      empty(modelVersion) ? {} : { version: modelVersion }
    )
  }
}

resource foundryUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  scope: account
  name: guid(account.id, principalId, foundryUserRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      foundryUserRoleId
    )
    principalId: principalId
    principalType: principalType
  }
}

output accountName string = account.name
output projectName string = project.name
output projectEndpoint string = '${account.properties.endpoints['AI Foundry API']}api/projects/${project.name}'
output modelDeploymentName string = modelDeployment.name
