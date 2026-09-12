{{/*
Chart name/labels helpers.
*/}}

{{- define "sentinelmesh.fullname" -}}
sentinelmesh
{{- end -}}

{{- define "sentinelmesh.labels" -}}
app.kubernetes.io/part-of: sentinelmesh
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "sentinelmesh.serviceLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/component: {{ .name }}
{{ include "sentinelmesh.labels" .root }}
{{- end -}}

{{- define "sentinelmesh.image" -}}
{{- $g := .root.Values.global -}}
{{- if $g.imageRegistry -}}
{{ $g.imageRegistry }}{{ $g.imageRepository }}:{{ $g.imageTag }}
{{- else -}}
{{ $g.imageRepository }}:{{ $g.imageTag }}
{{- end -}}
{{- end -}}

{{/*
Full env list for a service container: global.env (non-secret) + one
envFrom-style secretRef reference is handled in deployment.yaml directly;
this helper only renders the plain Env entries plus per-service overrides.
*/}}
{{- define "sentinelmesh.serviceEnv" -}}
- name: SM_SERVICE_NAME
  value: {{ .name }}
- name: SM_HTTP_PORT
  value: {{ .svc.port | quote }}
{{- if .svc.consumerGroup }}
- name: SM_KAFKA_CONSUMER_GROUP
  value: {{ .svc.consumerGroup }}
{{- end }}
{{- end -}}
