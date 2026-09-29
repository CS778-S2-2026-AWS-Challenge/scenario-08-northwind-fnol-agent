export const TO_BE_CONFIRMED = 'To be confirmed before release'

export const privacyContent = {
  common: {
    eyebrow: 'Your information',
    title: 'Privacy & your data',
    introduction: 'We use only the information needed to support your claim, keep it secure, and explain clearly when it is shared.',
    commitmentsHeading: 'Our privacy commitments',
    commitments: [
      {
        title: 'Only what is needed',
        text: 'We collect information that is reasonably necessary to start, assess, manage or complete your claim.',
      },
      {
        title: 'Shared with care',
        text: 'We share information only with the people and organisations that need it to provide the service, progress your claim, meet legal obligations or protect against fraud and misuse.',
      },
      {
        title: 'Your information, your rights',
        text: 'You can ask to access the personal information we hold about you or ask us to correct information that is inaccurate.',
      },
    ],
    currentClaim: {
      title: 'Information recorded for your current claim',
      text: 'Your claim record may contain the details you provide in this conversation, uploaded files, information received from approved claim participants, and system records needed to operate the service.',
      action: 'View information recorded for this claim',
    },
    sectionsBeforeProducts: [
      {
        id: 'about-this-notice',
        title: 'About this notice',
        blocks: [
          {
            type: 'parts',
            parts: [
              'This privacy notice explains how ',
              { config: 'organisation.legalName' },
              ' collects, uses, stores and shares personal information when you use ',
              { config: 'organisation.serviceName' },
              ' to start, manage or continue an insurance claim.',
            ],
          },
          {
            type: 'configuration',
            label: 'Insurer/service-provider relationship',
            config: 'serviceProviders.insurerRelationship',
          },
          {
            type: 'paragraph',
            text: 'This notice applies to Motor and Home & Contents claims handled through this service. It should be read together with any additional privacy notice provided by your insurer or another organisation involved in your claim.',
          },
        ],
      },
      {
        id: 'information-we-collect',
        title: 'Information we collect',
        blocks: [
          {
            type: 'paragraph',
            text: 'The information we collect depends on your claim, the services you use and the information needed to progress the claim.',
          },
          {
            type: 'subsection',
            title: 'Account and contact information',
            intro: 'We may collect:',
            items: [
              'Your name, contact details and preferred method of communication.',
              'Your policy, customer, claim or account identifiers.',
              'Information used to verify your identity or confirm that you are authorised to act for the policyholder.',
              'Communication preferences and accessibility requirements that are relevant to the service.',
            ],
          },
          {
            type: 'subsection',
            title: 'Claim and conversation information',
            intro: 'We may collect:',
            items: [
              'Information you provide through conversations, forms or other claim interactions.',
              'Photos, videos, documents, invoices, receipts, estimates and reports you upload.',
              'Dates, times, locations and descriptions of the event or loss.',
              'Details about other people involved in the claim, where relevant.',
              'Notes, summaries, status updates and correspondence relating to the claim.',
              'Feedback or support requests you send to us.',
            ],
          },
          {
            type: 'subsection',
            title: 'Payment information',
            paragraphs: [
              'Where needed to process an excess, reimbursement or settlement, we may collect payment or bank-account information. Payment card details may be processed directly by our payment provider rather than stored by us.',
            ],
          },
          {
            type: 'subsection',
            title: 'Technical and service information',
            intro: 'When you use the service, we may collect limited technical information, such as:',
            items: [
              'IP address, device type, browser and operating system.',
              'Login, session and authentication information.',
              'Dates and times of access.',
              'Error, performance, audit and security logs.',
              'Cookie or analytics information, where those tools are enabled.',
            ],
            paragraphs: [
              'We use this information to operate, protect and improve the service. Optional analytics or similar technologies should be identified separately where consent is required.',
            ],
          },
        ],
      },
    ],
    sectionsAfterProducts: [
      {
        id: 'how-we-collect-information',
        title: 'How we collect information',
        blocks: [
          {
            type: 'list',
            intro: 'We usually collect personal information directly from you when you:',
            items: [
              'Create or access an account.',
              'Start or continue a claim.',
              'Use the chat, forms or upload functions.',
              'Contact us for help.',
              'Review or correct claim information.',
              'Authorise another person or organisation to provide information.',
            ],
          },
          {
            type: 'list',
            intro: 'We may also collect information from other sources where permitted, including:',
            items: [
              'Your insurer, broker, policyholder or authorised representative.',
              'Other drivers, vehicle owners, household members, witnesses or people involved in the event.',
              'Assessors, loss adjusters, investigators, repairers, tradespeople, suppliers or service providers.',
              'Police, fire and emergency services.',
              'Relevant vehicle, property or public records.',
              'Fraud-prevention, identity-verification or security services.',
              'Connected devices or systems that you have authorised us to use.',
            ],
          },
          {
            type: 'paragraph',
            text: 'When required, we will take reasonable steps to tell you when we have collected personal information about you from another source, why it was collected, who may receive it and how you can access or correct it.',
          },
        ],
      },
      {
        id: 'how-we-use-your-information',
        title: 'How we use your information',
        blocks: [
          {
            type: 'list',
            intro: 'We may use personal information to:',
            items: [
              'Verify your identity, authority and policy or claim details.',
              'Create, assess, manage and complete your claim.',
              'Identify missing information and ask appropriate follow-up questions.',
              'Communicate with you about the claim and provide status updates.',
              'Arrange assessments, towing, repairs, restoration, temporary accommodation, replacement items or other claim services.',
              'Confirm facts, obtain estimates and validate documents.',
              'Calculate or support decisions about repairs, replacement, reimbursement or settlement.',
              'Detect, investigate and prevent fraud, misuse, security incidents or unlawful activity.',
              'Maintain accurate claim, financial and audit records.',
              'Respond to complaints, disputes and legal proceedings.',
              'Meet legal, regulatory and contractual obligations.',
              'Monitor the security, reliability and performance of the service.',
              'Improve our services using aggregated or de-identified information where reasonably possible.',
              'Carry out another purpose you have authorised or that is otherwise permitted by law.',
            ],
          },
          {
            type: 'paragraph',
            text: 'We will not use personal information for an unrelated purpose unless you have authorised that use or the use is otherwise permitted by law.',
          },
        ],
      },
      {
        id: 'use-of-ai-and-automated-tools',
        title: 'Use of AI and automated tools',
        blocks: [
          {
            type: 'parts',
            parts: [
              { config: 'organisation.serviceName' },
              ' may use automated tools to help:',
            ],
          },
          {
            type: 'bullets',
            items: [
              'Guide you through the claim process.',
              'Organise the information you provide.',
              'Identify information that may be missing.',
              'Summarise conversations and documents.',
              'Route information to the appropriate claim team or service provider.',
              'Detect security risks or unusual activity.',
            ],
          },
          {
            type: 'paragraph',
            text: 'These tools do not make the final decision about policy cover, liability, repairs, replacement or settlement. Those decisions are made or reviewed by authorised claim personnel.',
          },
          {
            type: 'parts',
            parts: [
              'Your messages and uploaded files may be processed by ',
              { config: 'serviceProviders.aiProvider' },
              ' acting on our instructions.',
            ],
          },
          {
            type: 'configuration',
            label: 'AI provider and model-training position',
            config: 'serviceProviders.modelTrainingPosition',
          },
          {
            type: 'paragraph',
            text: 'Do not enter information that is unrelated to your claim. If an automated summary appears incorrect, you can correct it or ask for a person to review it.',
          },
        ],
      },
      {
        id: 'who-we-may-share-information-with',
        title: 'Who we may share information with',
        blocks: [
          {
            type: 'list',
            intro: 'Where necessary and permitted, we may share relevant information with:',
            items: [
              'The insurer, claims administrator, policyholder or authorised representative.',
              'Reinsurers, where applicable.',
              'Assessors, loss adjusters, investigators and fraud-prevention specialists.',
              'Repairers, panel beaters, mechanics, towing companies and vehicle suppliers.',
              'Builders, engineers, valuers, restoration providers, tradespeople and contents suppliers.',
              'Temporary accommodation, transport or emergency-assistance providers.',
              'Payment, banking or settlement providers.',
              'Identity-verification and security providers.',
              'Hosting, communications, document-management, analytics and other technology providers working on our behalf.',
              'Professional advisers, auditors and legal representatives.',
              'Police, regulators, courts, government agencies or emergency services where disclosure is required or permitted by law.',
              'Another person or organisation you authorise us to contact.',
            ],
          },
          {
            type: 'paragraph',
            text: 'We limit the information shared to what is reasonably necessary for the relevant purpose.',
          },
        ],
      },
      {
        id: 'overseas-storage-and-processing',
        title: 'Overseas storage and processing',
        blocks: [
          {
            type: 'parts',
            parts: [
              'We and our service providers may store or process personal information in ',
              { config: 'hostingLocations' },
              '.',
            ],
          },
          {
            type: 'paragraph',
            text: 'Where personal information is disclosed to an organisation outside New Zealand, we take steps required by applicable privacy law to ensure that the information receives appropriate protection. These steps may include confirming that the recipient is subject to comparable privacy safeguards or requiring suitable protections in our contract with the recipient.',
          },
          {
            type: 'paragraph',
            text: 'If comparable safeguards do not apply and your authorisation is required, we will explain the relevant privacy implications before asking you to authorise the disclosure.',
          },
        ],
      },
      {
        id: 'security',
        title: 'Security',
        blocks: [
          {
            type: 'paragraph',
            text: 'We use administrative, technical and physical safeguards appropriate to the nature of the information we hold.',
          },
          {
            type: 'paragraph',
            text: 'These may include access controls, authentication, monitoring, secure transmission and storage, staff training and processes for responding to security incidents.',
          },
          {
            type: 'paragraph',
            text: 'No system can guarantee absolute security. If a privacy breach occurs that has caused or may cause serious harm, we will notify affected people and the Office of the Privacy Commissioner when required by law.',
          },
        ],
      },
      {
        id: 'how-long-we-keep-information',
        title: 'How long we keep information',
        blocks: [
          {
            type: 'paragraph',
            text: 'We retain personal information only for as long as it is reasonably required for the purposes described in this notice or to meet legal, regulatory, financial, fraud-prevention and dispute-resolution requirements.',
          },
          {
            type: 'configuration-list',
            intro: 'Complete the applicable periods before publication:',
            items: [
              ['Claim records', 'retentionPeriods.claimRecords'],
              ['Account information', 'retentionPeriods.accountInformation'],
              ['Conversation and uploaded-file records', 'retentionPeriods.conversationAndUploads'],
              ['Security and technical logs', 'retentionPeriods.securityAndTechnicalLogs'],
              ['Optional analytics information', 'retentionPeriods.optionalAnalytics'],
            ],
          },
          {
            type: 'paragraph',
            text: 'When information is no longer required, we take reasonable steps to delete it, securely destroy it or de-identify it.',
          },
        ],
      },
      {
        id: 'your-rights-and-choices',
        title: 'Your rights and choices',
        blocks: [
          {
            type: 'list',
            intro: 'You may ask us to:',
            items: [
              'Confirm whether we hold personal information about you.',
              'Provide access to personal information we hold about you.',
              'Correct information that is inaccurate, incomplete or out of date.',
              'Add a statement of correction where we do not make the correction you requested.',
              'Review information produced or summarised by an automated tool.',
              'Withdraw an optional consent or change an optional communication preference.',
              'Consider a deletion request where deletion is legally and operationally available.',
            ],
          },
          {
            type: 'paragraph',
            text: 'A deletion request may not result in the immediate removal of all information. We may need to retain claim records to meet legal obligations, administer the policy, resolve disputes, prevent fraud or preserve an accurate historical record.',
          },
          {
            type: 'paragraph',
            text: 'We may need to verify your identity and authority before responding. Legal exceptions may also limit the information we can provide.',
          },
          {
            type: 'paragraph',
            text: 'To make a request, contact us using the details below.',
          },
        ],
      },
      {
        id: 'information-about-other-people',
        title: 'Information about other people',
        blocks: [
          {
            type: 'paragraph',
            text: 'A claim may require information about drivers, passengers, witnesses, household members, tenants, neighbours or other affected people.',
          },
          {
            type: 'list',
            intro: 'If you provide another person’s information, please:',
            items: [
              'Provide only information that is relevant to the claim.',
              'Make reasonable efforts to ensure it is accurate.',
              'Confirm that you are authorised or otherwise permitted to provide it.',
              'Tell the person about this privacy notice where it is reasonable to do so.',
            ],
          },
          {
            type: 'paragraph',
            text: 'We may contact that person directly when necessary to verify the information or meet our privacy obligations.',
          },
        ],
      },
      {
        id: 'what-happens-if-information-is-not-provided',
        title: 'What happens if information is not provided',
        blocks: [
          {
            type: 'list',
            intro: 'You may choose not to provide personal information. However, if required information is missing, we may be unable to:',
            items: [
              'Verify your identity or authority.',
              'Create or progress the claim.',
              'Assess the cause or extent of the loss.',
              'Arrange repairs, replacement, assistance or settlement.',
              'Provide some features of the service.',
            ],
          },
          {
            type: 'paragraph',
            text: 'We will identify optional information where reasonably possible.',
          },
        ],
      },
      {
        id: 'contact-us',
        title: 'Contact us',
        blocks: [
          {
            type: 'paragraph',
            text: 'If you have a privacy question, want to access or correct your information, or wish to make a complaint, contact:',
          },
          { type: 'privacy-contact' },
          {
            type: 'paragraph',
            text: 'Please do not send identity documents or sensitive claim information by ordinary email unless we ask you to use that channel.',
          },
        ],
      },
      {
        id: 'making-a-complaint',
        title: 'Making a complaint',
        blocks: [
          {
            type: 'paragraph',
            text: 'Please contact our Privacy Officer first so that we can investigate and respond.',
          },
          {
            type: 'paragraph',
            text: 'If you are not satisfied with our response, you can contact the New Zealand Office of the Privacy Commissioner:',
          },
          { type: 'privacy-commissioner-contact' },
        ],
      },
      {
        id: 'changes-to-this-notice',
        title: 'Changes to this notice',
        blocks: [
          {
            type: 'paragraph',
            text: 'We may update this notice when our services, data practices or legal obligations change.',
          },
          {
            type: 'paragraph',
            text: 'The date at the top of the page shows when the notice was last updated. If a change materially affects how we handle your information, we will provide additional notice where appropriate.',
          },
        ],
      },
    ],
  },
  motor: {
    id: 'information-collected-motor',
    title: 'Information collected for a Motor claim',
    intro: 'For a Motor claim, we may collect information about:',
    items: [
      'The insured vehicle, including its registration, make, model, year, VIN or chassis number, mileage and condition.',
      'The policyholder, vehicle owner and people who were driving or responsible for the vehicle.',
      'Driver licence details, where reasonably required to verify the driver or assess the claim.',
      'The date, time, location and circumstances of the accident, theft, damage or other event.',
      'Damage to the insured vehicle or other property.',
      'Other drivers, vehicle owners, passengers, witnesses or affected people.',
      'Police event or report numbers and information supplied by emergency services, where relevant.',
      'Photos, videos, dash-camera footage, diagrams or descriptions of the event and damage.',
      'Towing, storage, inspection, repair and replacement information.',
      'Repairer, mechanic, panel beater, assessor or vehicle supplier reports and estimates.',
      'Vehicle ownership, finance or leasing information, where relevant to the claim.',
      'Telematics, GPS or connected-vehicle information only where it is relevant, lawfully available and clearly disclosed.',
      'Injury, accessibility or support information only where it is necessary to provide assistance or manage the claim.',
    ],
    closing: 'Please provide information about another person only when it is relevant to the claim and you are authorised or otherwise permitted to provide it.',
  },
  homeContents: {
    id: 'information-collected-home-contents',
    title: 'Information collected for a Home & Contents claim',
    intro: 'For a Home & Contents claim, we may collect information about:',
    items: [
      'The insured property, including its address, type, occupancy and use.',
      'Your relationship to the property, such as owner, tenant, landlord, mortgagee or authorised representative.',
      'The date, time, location, cause and circumstances of the damage, loss or theft.',
      'The affected building areas, fixtures, fittings and personal belongings.',
      'Descriptions, photographs, videos, receipts, valuations, serial numbers, warranty information and proof of ownership for affected items.',
      'The age, condition, purchase price and estimated replacement or repair cost of affected property.',
      'Building, inspection, engineering, restoration, repair or replacement reports and estimates.',
      'Information from builders, plumbers, electricians, engineers, quantity surveyors, valuers, cleaners, restoration providers or other tradespeople.',
      'Alarm, security-system, fire-service, police or emergency-service information, where relevant.',
      'Details about household members, tenants, guests, neighbours, witnesses or other affected people.',
      'Temporary accommodation, accessibility or urgent-support requirements.',
      'Mortgage, tenancy, body corporate or property-management information, where relevant.',
      'Information needed to arrange repairs, replacement items, emergency work or settlement.',
    ],
    closing: 'Please avoid including sensitive or unrelated information about household members or other people.',
  },
  organisation: {
    legalName: null,
    address: null,
    serviceName: null,
    websiteUrl: null,
  },
  serviceProviders: {
    insurerRelationship: null,
    aiProvider: null,
    modelTrainingPosition: null,
  },
  hostingLocations: [],
  retentionPeriods: {
    claimRecords: null,
    accountInformation: null,
    conversationAndUploads: null,
    securityAndTechnicalLogs: null,
    optionalAnalytics: null,
  },
  contact: {
    privacyOfficerEmail: null,
    privacyOfficerPhone: null,
  },
  lastUpdated: {
    prototype: '29 September 2026',
    production: null,
  },
  prototypeNotice: 'Prototype privacy content — operational and legal details must be approved before release.',
}

export const requiredProductionConfiguration = [
  'organisation.legalName',
  'organisation.address',
  'organisation.serviceName',
  'organisation.websiteUrl',
  'serviceProviders.insurerRelationship',
  'serviceProviders.aiProvider',
  'serviceProviders.modelTrainingPosition',
  'hostingLocations',
  'retentionPeriods.claimRecords',
  'retentionPeriods.accountInformation',
  'retentionPeriods.conversationAndUploads',
  'retentionPeriods.securityAndTechnicalLogs',
  'retentionPeriods.optionalAnalytics',
  'contact.privacyOfficerEmail',
  'contact.privacyOfficerPhone',
  'lastUpdated.production',
]

export function readPrivacyConfiguration(path, content = privacyContent) {
  const value = path.split('.').reduce((current, key) => current?.[key], content)
  if (Array.isArray(value)) return value.length > 0 ? value.join(', ') : TO_BE_CONFIRMED
  return value || TO_BE_CONFIRMED
}

export function unresolvedPrivacyConfiguration(content = privacyContent) {
  return requiredProductionConfiguration.filter(
    (path) => readPrivacyConfiguration(path, content) === TO_BE_CONFIRMED,
  )
}

export function productPrivacySections(claimFamily) {
  if (claimFamily === 'motor') {
    return [
      { ...privacyContent.motor, relevance: 'current' },
      { ...privacyContent.homeContents, relevance: 'other' },
    ]
  }
  if (claimFamily === 'homeContents') {
    return [
      { ...privacyContent.homeContents, relevance: 'current' },
      { ...privacyContent.motor, relevance: 'other' },
    ]
  }
  return [
    { ...privacyContent.motor, relevance: 'equal' },
    { ...privacyContent.homeContents, relevance: 'equal' },
  ]
}
