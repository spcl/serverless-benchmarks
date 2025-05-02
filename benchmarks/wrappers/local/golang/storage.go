package golang

import (
    "bytes"
    "context"
    "fmt"
    "io"
    "os"
    "path/filepath"
    "strconv"
    "strings"

    "github.com/google/uuid"
    "github.com/minio/minio-go/v7"
    "github.com/minio/minio-go/v7/pkg/credentials"
)

type Storage struct {
    client *minio.Client
}

var instance *Storage

func UniqueName(name string) string {
    ext := filepath.Ext(name)
    basename := name[:len(name)-len(ext)]
    uuidStr := strings.Split(uuid.New().String(), "-")[0]
    return fmt.Sprintf("%s.%s%s", basename, uuidStr, ext)
}

func NewStorage() (*Storage, error) {
    address, exists := os.LookupEnv("MINIO_ADDRESS")
    if !exists {
        return nil, nil
    }
    
    accessKey := os.Getenv("MINIO_ACCESS_KEY")
    secretKey := os.Getenv("MINIO_SECRET_KEY")
    
    parts := strings.Split(address, ":")
    endpoint := parts[0]
    var port int = 9000 // Default port
    
    if len(parts) > 1 {
        var err error
        port, err = strconv.Atoi(parts[1])
        if err != nil {
            return nil, fmt.Errorf("invalid port in MINIO_ADDRESS: %v", err)
        }
    }

    client, err := minio.New(endpoint, &minio.Options{
        Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
        Secure: false,
        Port:   uint16(port),
    })
    if err != nil {
        return nil, err
    }

    return &Storage{client: client}, nil
}

func (s *Storage) Upload(bucket, file, filepath string) (string, error) {
    keyName := UniqueName(file)
    _, err := s.client.FPutObject(context.Background(), bucket, keyName, filepath, minio.PutObjectOptions{})
    if err != nil {
        return "", err
    }
    return keyName, nil
}

func (s *Storage) Download(bucket, file, filepath string) error {
    return s.client.FGetObject(context.Background(), bucket, file, filepath, minio.GetObjectOptions{})
}

func (s *Storage) DownloadDirectory(bucket, prefix, path string) error {
    ctx := context.Background()
    objects := s.client.ListObjects(ctx, bucket, minio.ListObjectsOptions{
        Prefix:    prefix,
        Recursive: true,
    })

    for object := range objects {
        if object.Err != nil {
            return object.Err
        }
        
        objectPath := filepath.Join(path, object.Key)
        if err := os.MkdirAll(filepath.Dir(objectPath), 0755); err != nil {
            return err
        }
        
        if err := s.Download(bucket, object.Key, objectPath); err != nil {
            return err
        }
    }
    
    return nil
}

func (s *Storage) UploadStream(bucket, file string, data []byte) (string, error) {
    keyName := UniqueName(file)
    reader := bytes.NewReader(data)
    _, err := s.client.PutObject(context.Background(), bucket, keyName, reader, int64(len(data)), minio.PutObjectOptions{})
    if err != nil {
        return "", err
    }
    return keyName, nil
}

func (s *Storage) DownloadStream(bucket, file string) ([]byte, error) {
    obj, err := s.client.GetObject(context.Background(), bucket, file, minio.GetObjectOptions{})
    if err != nil {
        return nil, err
    }
    defer obj.Close()
    
    return io.ReadAll(obj)
}

func GetInstance() (*Storage, error) {
    if instance == nil {
        var err error
        instance, err = NewStorage()
        if err != nil {
            return nil, err
        }
    }
    return instance, nil
}